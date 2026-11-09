"""Days 14-20: NetworkComplianceOrchestrator. Every interval, compare every device with its
intent and the compliance policy, keep the result as queryable state, and start a child
workflow to deal with each drift: never two for one device, never too many at once."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import SearchAttributePair, TypedSearchAttributes
from temporalio.exceptions import ChildWorkflowError, WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from netops_temporal.models import (
        ComplianceState,
        DriftReport,
        OrchestratorInput,
        RemediationRequest,
        SetIntervalRequest,
        UpgradeRequest,
    )
    from netops_temporal.observability import DEVICE_SA
    from netops_temporal.workflows.compliance_cycle import collect_compliance
    from netops_temporal.workflows.remediation import ConfigRemediationWorkflow
    from netops_temporal.workflows.upgrade import DeviceUpgradeWorkflow


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

    @workflow.run
    async def run(self, inp: OrchestratorInput) -> None:
        cycles_this_run = 0
        while True:
            # One cycle: check every device in parallel. Day 18 moved the check into
            # compliance_cycle.py, so the nightly audit runs exactly the same one.
            results = list((await collect_compliance(inp.devices)).values())
            self.state.update({s.device: s for s in results})
            # Day 15: one child workflow per drift, all running in parallel.
            await asyncio.gather(
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
                        }
                    )
                )

    async def remediate(self, state: ComplianceState, dry_run: bool) -> None:
        outcomes = await asyncio.gather(*(self.run_child(d, dry_run) for d in state.drift))
        state.remediation = "; ".join(outcomes)

    async def run_child(self, drift: DriftReport, dry_run: bool) -> str:
        try:
            if drift.kind == "config":
                async with self.remediation_slots:
                    try:
                        result = await workflow.execute_child_workflow(
                            ConfigRemediationWorkflow.run,
                            RemediationRequest(
                                device=drift.device,
                                missing_lines=drift.missing_lines,
                                dry_run=dry_run,
                            ),
                            # The ID is the lock: only one running remediation per device.
                            id=f"remediate-config-{drift.device}",
                            # Day 20: findable by device, and readable at a glance in the UI.
                            search_attributes=TypedSearchAttributes(
                                [SearchAttributePair(DEVICE_SA, drift.device)]
                            ),
                            static_summary=(
                                f"config remediation for {drift.device}"
                                + (" (dry run)" if dry_run else "")
                            ),
                            static_details="Missing lines:\n"
                            + "\n".join(f"- `{line}`" for line in drift.missing_lines),
                            # If the orchestrator is cancelled or terminated, ask this child to
                            # stop too: a config change shouldn't run on unsupervised.
                            parent_close_policy=ParentClosePolicy.REQUEST_CANCEL,
                        )
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

    @workflow.update
    def set_interval(self, req: SetIntervalRequest) -> int:
        self.interval_seconds = req.interval_seconds
        return self.interval_seconds

    @set_interval.validator
    def validate_set_interval(self, req: SetIntervalRequest) -> None:
        if not 30 <= req.interval_seconds <= 86400:
            raise ValueError("interval must be 30..86400 seconds")
