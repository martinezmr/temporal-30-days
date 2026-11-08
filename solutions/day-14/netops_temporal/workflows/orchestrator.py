"""Day 14: NetworkComplianceOrchestrator v0. Every interval, compare every device with its
intent and the compliance policy, and keep the result as queryable state. No remediation yet."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.backup import fetch_device_intent
    from netops_temporal.activities.compliance import check_config_compliance
    from netops_temporal.activities.facts import get_device_facts
    from netops_temporal.drift import compute_drift
    from netops_temporal.models import (
        ComplianceCheckRequest,
        ComplianceState,
        FactsRequest,
        IntentRequest,
        OrchestratorInput,
        SetIntervalRequest,
    )
    from netops_temporal.policies import POLICIES

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

    @workflow.run
    async def run(self, inp: OrchestratorInput) -> None:
        cycles_this_run = 0
        while True:
            # One cycle: check every device in parallel (Day 7's fan-out).
            results = await asyncio.gather(*(self.check_device(d) for d in inp.devices))
            self.state.update({s.device: s for s in results})
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
