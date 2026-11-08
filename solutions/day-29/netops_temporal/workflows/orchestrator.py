"""Days 14-29: NetworkComplianceOrchestrator. Every interval, compare every device with its
intent and the compliance policy, keep the result as queryable state, and start a child
workflow to deal with each drift: never two for one device, never too many at once.

Day 29: a config fix the model calls risky waits for an operator's decision first."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, SearchAttributePair, TypedSearchAttributes
from temporalio.exceptions import (
    ActivityError,
    ChildWorkflowError,
    NexusOperationError,
    WorkflowAlreadyStartedError,
)
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.explain import explain_drift
    from netops_temporal.constants import COMPLIANCE_ENDPOINT, DEVICE_IO_TASK_QUEUE
    from netops_temporal.models import (
        ComplianceState,
        DeviceDecision,
        DriftReport,
        ExplainRequest,
        OrchestratorInput,
        PendingApproval,
        RemediationRequest,
        RemediationResult,
        SetIntervalRequest,
        UpgradeRequest,
    )
    from netops_temporal.nexus.service import ComplianceService
    from netops_temporal.observability import DEVICE_SA
    from netops_temporal.workflows.compliance_cycle import collect_compliance
    from netops_temporal.workflows.remediation import ConfigRemediationWorkflow
    from netops_temporal.workflows.upgrade import DeviceUpgradeWorkflow


async def gather_all(*aws):
    """asyncio.gather, except that a cancellation waits for every task to finish cancelling.

    Plain gather raises as soon as the first task is cancelled (say, one waiting for a
    remediation slot) and leaves the rest running. The workflow would then close while Nexus
    operations are still being cancelled, and the cancellation would never reach them (Day 23).
    """
    tasks = [asyncio.ensure_future(aw) for aw in aws]
    try:
        return await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        await workflow.wait(tasks)  # asyncio.wait, in a deterministic order
        raise


@workflow.defn
class NetworkComplianceOrchestrator:
    @workflow.init
    def __init__(self, inp: OrchestratorInput) -> None:
        self.state: dict[str, ComplianceState] = dict(inp.state)
        self._cycles = inp.cycles
        self.interval_seconds = inp.interval_seconds
        self.check_requested = False
        # Day 16: asyncio.Semaphore works in workflows like asyncio.Lock (Day 13): at most
        # this many config remediations hold a slot at the same time.
        self.remediation_slots = asyncio.Semaphore(inp.max_parallel_remediations)
        self.change_ticket = inp.change_ticket
        # Day 29: fixes waiting for an operator, and decisions not yet acted on, by device.
        self.pending: dict[str, PendingApproval] = dict(inp.pending)
        self.decisions: dict[str, DeviceDecision] = dict(inp.decisions)
        self.approval_risks = inp.approval_risks
        self.approval_wait_seconds = inp.approval_wait_seconds

    @workflow.run
    async def run(self, inp: OrchestratorInput) -> None:
        cycles_this_run = 0
        while True:
            # One cycle: check every device in parallel. Day 18 moved the check into
            # compliance_cycle.py, so the nightly audit runs exactly the same one.
            results = list((await collect_compliance(inp.devices)).values())
            # Day 25: a language model explains each drift. Calling it is a new command, so
            # orchestrators that started before this change skip it (Day 19).
            if workflow.patched("explain-drift"):
                await gather_all(*(self.explain(s) for s in results if s.status == "drifted"))
            self.state.update({s.device: s for s in results})
            # Day 29: a device that no longer drifts has nothing left to approve.
            for s in results:
                if s.status != "drifted":
                    self.pending.pop(s.device, None)
                    self.decisions.pop(s.device, None)
            # Day 15: one child workflow per drift, all running in parallel.
            await gather_all(
                *(self.remediate(s, inp.dry_run) for s in results if s.status == "drifted")
            )
            self._cycles += 1
            cycles_this_run += 1
            # Day 20: what the UI shows under "Current Details" for this workflow.
            workflow.set_current_details(self.details_table())
            workflow.logger.info(
                "cycle %d: %s",
                self._cycles,
                {d: s.status for d, s in sorted(self.state.items())},
            )

            self.check_requested = False
            try:
                await workflow.wait_condition(
                    lambda: self.check_requested,
                    timeout=timedelta(seconds=self.interval_seconds),
                )
            except TimeoutError:
                pass

            # Day 12: hand over to a fresh run before history grows too long.
            if (
                workflow.info().is_continue_as_new_suggested()
                or cycles_this_run >= inp.max_cycles_per_run
            ):
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(
                    inp.model_copy(
                        update={
                            "state": self.state,
                            "cycles": self._cycles,
                            "interval_seconds": self.interval_seconds,
                            "pending": self.pending,
                            "decisions": self.decisions,
                        }
                    )
                )

    async def explain(self, state: ComplianceState) -> None:
        previous = self.state.get(state.device)
        if previous and previous.explanation and previous.drift == state.drift:
            # The same drift as last cycle: keep the answer instead of paying for it again.
            state.explanation = previous.explanation
            return
        try:
            state.explanation = await workflow.execute_activity(
                explain_drift,
                ExplainRequest(device=state.device, drift=state.drift),
                task_queue=DEVICE_IO_TASK_QUEUE,
                start_to_close_timeout=timedelta(seconds=60),
                # Rate limits and malformed answers get three more tries; a bad token none.
                retry_policy=RetryPolicy(maximum_attempts=4),
            )
        except ActivityError as err:
            # No explanation is a shame, not a reason to stop checking devices.
            workflow.logger.warning("no explanation for %s: %s", state.device, err.cause)

    async def remediate(self, state: ComplianceState, dry_run: bool) -> None:
        outcomes = await gather_all(*(self.run_child(d, state, dry_run) for d in state.drift))
        state.remediation = "; ".join(outcomes)

    async def approval(self, drift: DriftReport, state: ComplianceState) -> DeviceDecision | None:
        """Day 29: hold a risky config fix until an operator decides (Day 27's pattern, keyed
        by device). None if nobody decided within approval_wait_seconds: the device stays
        pending, and the next cycle asks again."""
        risk = state.explanation.risk if state.explanation else "unknown"
        self.pending[drift.device] = PendingApproval(
            device=drift.device,
            missing_lines=drift.missing_lines,
            risk=risk,
            summary=state.explanation.summary if state.explanation else "",
        )
        try:
            await workflow.wait_condition(
                lambda: drift.device in self.decisions,
                timeout=timedelta(seconds=self.approval_wait_seconds),
            )
        except TimeoutError:
            return None
        del self.pending[drift.device]
        return self.decisions.pop(drift.device)

    def needs_approval(self, state: ComplianceState, dry_run: bool) -> bool:
        if dry_run or not self.approval_risks:
            return False  # a dry run changes nothing; no risks listed means no gate
        # No explanation (the model was down) means nobody knows the risk: ask.
        return state.explanation is None or state.explanation.risk in self.approval_risks

    async def run_child(self, drift: DriftReport, state: ComplianceState, dry_run: bool) -> str:
        try:
            if drift.kind == "config":
                ticket = self.change_ticket
                if self.needs_approval(state, dry_run):
                    decision = await self.approval(drift, state)
                    if decision is None:
                        risk = self.pending[drift.device].risk
                        return f"config: waiting for approval ({risk} risk)"
                    if not decision.approve:
                        return f"config: rejected by {decision.approver}"
                    # The approval is part of the change record (Day 24's REQUIRE_TICKET).
                    approved = f"approved by {decision.approver}"
                    ticket = f"{ticket}, {approved}" if ticket else approved
                async with self.remediation_slots:
                    # Day 23: the compliance team runs remediations now, behind their Nexus
                    # service. A Nexus operation instead of a child is a different command,
                    # so orchestrators from before keep starting children (Day 19).
                    if workflow.patched("remediate-via-nexus"):
                        try:
                            result = await self.remediate_via_nexus(drift, dry_run, ticket)
                        except NexusOperationError as err:
                            # The handler's message, e.g. "remediate-config-bos-acc-01 already
                            # running" when someone else holds the ID (Day 16's lock).
                            reason = err.cause.message if err.cause else err.message
                            return f"config: {reason}"
                    else:
                        try:
                            result = await self.remediate_as_child(drift, dry_run)
                        except WorkflowAlreadyStartedError:
                            # Someone (an operator, or a previous orchestrator) is already
                            # remediating this device. Don't start a second one.
                            return f"config: remediate-config-{drift.device} already running"
                if dry_run:
                    return f"config: dry run, would add {len(drift.missing_lines)} line(s)"
                if result.ok:
                    return f"config: pushed {len(result.pushed_lines)} line(s)"
                undone = "rolled back" if result.rolled_back else "nothing changed"
                return f"config: failed ({undone}): {result.error}"
            # An upgrade can wait hours for its window, so the cycle doesn't wait for it:
            # start it and move on. ABANDON: it must never be cut off halfway, whatever
            # happens to the orchestrator.
            try:
                await workflow.start_child_workflow(
                    DeviceUpgradeWorkflow.run,
                    UpgradeRequest(device=drift.device, target_version=drift.expected),
                    id=f"upgrade-{drift.device}",
                    search_attributes=TypedSearchAttributes(
                        [SearchAttributePair(DEVICE_SA, drift.device)]
                    ),
                    static_summary=f"upgrade {drift.device} to {drift.expected}",
                    parent_close_policy=ParentClosePolicy.ABANDON,
                )
            except WorkflowAlreadyStartedError:
                # The last cycle's upgrade is still running: same ID, so no second one.
                return f"upgrade: upgrade-{drift.device} already running"
            return f"upgrade: started upgrade-{drift.device}"
        except ChildWorkflowError as err:
            return f"{drift.kind}: failed: {err.cause}"

    async def remediate_via_nexus(
        self, drift: DriftReport, dry_run: bool, ticket: str | None
    ) -> RemediationResult:
        compliance = workflow.create_nexus_client(
            service=ComplianceService, endpoint=COMPLIANCE_ENDPOINT
        )
        # Waits for the remediation workflow's result, in the compliance namespace. If this
        # orchestrator is cancelled, the operation (and so the workflow) is cancelled too.
        return await compliance.execute_operation(
            ComplianceService.remediate,
            RemediationRequest(
                device=drift.device,
                missing_lines=drift.missing_lines,
                dry_run=dry_run,
                change_ticket=ticket,  # Day 24; Day 29 adds who approved it
            ),
        )

    async def remediate_as_child(self, drift: DriftReport, dry_run: bool) -> RemediationResult:
        """Days 15-22: the remediation as a child workflow, in this namespace."""
        return await workflow.execute_child_workflow(
            ConfigRemediationWorkflow.run,
            RemediationRequest(
                device=drift.device,
                missing_lines=drift.missing_lines,
                dry_run=dry_run,
            ),
            # The ID is the lock: only one running remediation per device.
            id=f"remediate-config-{drift.device}",
            # Day 20: findable by device, and readable at a glance in the UI.
            search_attributes=TypedSearchAttributes([SearchAttributePair(DEVICE_SA, drift.device)]),
            static_summary=(
                f"config remediation for {drift.device}" + (" (dry run)" if dry_run else "")
            ),
            static_details="Missing lines:\n"
            + "\n".join(f"- `{line}`" for line in drift.missing_lines),
            # If the orchestrator is cancelled or terminated, ask this child to stop too: a
            # config change shouldn't run on unsupervised.
            parent_close_policy=ParentClosePolicy.REQUEST_CANCEL,
        )

    def details_table(self) -> str:
        """A markdown table of the latest state. The UI renders it."""
        rows = [
            f"| {d} | {s.status} | {s.remediation or s.error or ''} |"
            for d, s in sorted(self.state.items())
        ]
        return "\n".join(
            [
                f"**cycle {self._cycles}** at {workflow.now():%Y-%m-%d %H:%M:%S} UTC",
                "",
                "| Device | Status | Last action |",
                "| --- | --- | --- |",
                *rows,
            ]
        )

    @workflow.query
    def compliance(self) -> dict[str, ComplianceState]:
        return self.state

    @workflow.query
    def cycles(self) -> int:
        return self._cycles

    @workflow.signal
    def force_check(self) -> None:
        self.check_requested = True

    @workflow.query
    def pending_approvals(self) -> list[PendingApproval]:
        """Day 29: config fixes waiting for a decision."""
        return list(self.pending.values())

    # Day 29: Day 27's update and validator, keyed by device.
    @workflow.update
    def decide(self, decision: DeviceDecision) -> str:
        self.decisions[decision.device] = decision
        return "approved" if decision.approve else "rejected"

    @decide.validator
    def check_decision(self, decision: DeviceDecision) -> None:
        if decision.device not in self.pending or decision.device in self.decisions:
            raise ValueError(f"{decision.device} isn't waiting for approval")
        if not decision.approver:
            raise ValueError("a decision needs an approver")

    @workflow.update
    def set_interval(self, req: SetIntervalRequest) -> int:
        self.interval_seconds = req.interval_seconds
        return self.interval_seconds

    @set_interval.validator
    def validate_set_interval(self, req: SetIntervalRequest) -> None:
        if not 30 <= req.interval_seconds <= 86400:
            raise ValueError("interval must be 30..86400 seconds")
