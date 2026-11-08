"""Days 14-16: NetworkComplianceOrchestrator. Every interval, compare every device with its
intent and the compliance policy, keep the result as queryable state, and start a child
workflow to deal with each drift: never two for one device, never too many at once."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError, WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.backup import fetch_device_intent
    from netops_temporal.activities.compliance import check_config_compliance
    from netops_temporal.activities.facts import get_device_facts
    from netops_temporal.drift import compute_drift
    from netops_temporal.models import (
        ComplianceCheckRequest,
        ComplianceState,
        DriftReport,
        FactsRequest,
        IntentRequest,
        OrchestratorInput,
        RemediationRequest,
        SetIntervalRequest,
        UpgradeRequest,
    )
    from netops_temporal.policies import POLICIES
    from netops_temporal.workflows.remediation import ConfigRemediationWorkflow
    from netops_temporal.workflows.upgrade import DeviceUpgradeWorkflow

ACTIVITY_OPTIONS = {
    "start_to_close_timeout": timedelta(seconds=60),
    "retry_policy": RetryPolicy(maximum_attempts=3),
}


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
            # One cycle: check every device in parallel (Day 7's fan-out).
            results = await asyncio.gather(*(self.check_device(d) for d in inp.devices))
            self.state.update({s.device: s for s in results})
            # Day 15: one child workflow per drift, all running in parallel.
            await asyncio.gather(
                *(self.remediate(s, inp.dry_run) for s in results if s.status == "drifted")
            )
            self._cycles += 1
            cycles_this_run += 1
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

    async def check_device(self, device: str) -> ComplianceState:
        """Intent and facts in parallel, then the config check for the device's role.

        An unreachable device becomes `unknown` with the reason: one bad device never stops
        the cycle for the others.
        """
        try:
            intent, facts = await asyncio.gather(
                workflow.execute_activity(
                    fetch_device_intent, IntentRequest(device=device), **ACTIVITY_OPTIONS
                ),
                workflow.execute_activity(
                    get_device_facts, FactsRequest(device=device), **ACTIVITY_OPTIONS
                ),
            )
            missing = await workflow.execute_activity(
                check_config_compliance,
                ComplianceCheckRequest(device=device, required_lines=POLICIES[intent.role]),
                **ACTIVITY_OPTIONS,
            )
        except ActivityError as err:
            return ComplianceState(
                device=device, status="unknown", checked_at=workflow.now(), error=str(err.cause)
            )
        # Deterministic logic can live in the workflow. Only I/O needs to be an activity.
        drift = compute_drift(intent, facts, missing)
        return ComplianceState(
            device=device,
            status="drifted" if drift else "compliant",
            drift=drift,
            checked_at=workflow.now(),
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
                    parent_close_policy=ParentClosePolicy.ABANDON,
                )
            except WorkflowAlreadyStartedError:
                # The last cycle's upgrade is still running: same ID, so no second one.
                return f"upgrade: upgrade-{drift.device} already running"
            return f"upgrade: started upgrade-{drift.device}"
        except ChildWorkflowError as err:
            return f"{drift.kind}: failed: {err.cause}"

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
