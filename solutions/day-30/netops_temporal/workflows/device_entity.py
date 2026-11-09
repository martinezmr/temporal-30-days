"""Day 13: the entity pattern. One workflow per device, and every operation goes through it."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, VersioningBehavior
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.backup import backup_running_config
    from netops_temporal.activities.facts import get_device_facts
    from netops_temporal.constants import DEVICE_IO_TASK_QUEUE
    from netops_temporal.models import (
        BackupConfigRequest,
        DeviceEntityInput,
        FactsRequest,
        OperationRequest,
        OperationResult,
    )
    from netops_temporal.versioning import behavior

ACTIVITY_OPTIONS = {
    # Day 21: every activity runs on the device-io workers.
    "task_queue": DEVICE_IO_TASK_QUEUE,
    "start_to_close_timeout": timedelta(seconds=60),
    "retry_policy": RetryPolicy(maximum_attempts=3),
}


# Day 30: lives as long as the device does: moves to each new build.
@workflow.defn(versioning_behavior=behavior(VersioningBehavior.AUTO_UPGRADE))
class DeviceEntityWorkflow:
    @workflow.init
    def __init__(self, inp: DeviceEntityInput) -> None:
        self.device = inp.device
        self.recent: list[OperationResult] = list(inp.recent)
        self.ops_this_run = 0
        # asyncio.Lock is safe in a workflow: Temporal runs workflow code on its own
        # deterministic event loop. Holding it means "I'm the one talking to this device".
        self.lock = asyncio.Lock()

    @workflow.run
    async def run(self, inp: DeviceEntityInput) -> None:
        # The entity does nothing on its own. It waits; the work happens in `submit`.
        await workflow.wait_condition(
            lambda: (
                self.ops_this_run >= inp.max_ops_per_run
                or workflow.info().is_continue_as_new_suggested()
            )
        )
        # Day 12's rules: let queued operations finish, then hand over to a fresh run.
        await workflow.wait_condition(workflow.all_handlers_finished)
        workflow.continue_as_new(
            DeviceEntityInput(
                device=self.device, max_ops_per_run=inp.max_ops_per_run, recent=self.recent[-20:]
            )
        )

    # An async update handler can await activities. Several can be in flight at once, so the
    # lock makes them take turns: operations on one device never overlap.
    @workflow.update
    async def submit(self, op: OperationRequest) -> OperationResult:
        async with self.lock:
            try:
                detail = await self._run_operation(op)
                result = OperationResult(
                    kind=op.kind, requested_by=op.requested_by, ok=True, detail=detail
                )
            except ActivityError as err:
                result = OperationResult(
                    kind=op.kind, requested_by=op.requested_by, ok=False, detail=str(err.cause)
                )
            self.recent.append(result)
            self.ops_this_run += 1
            return result

    @submit.validator
    def validate_submit(self, op: OperationRequest) -> None:
        if not op.requested_by.strip():
            raise ValueError("requested_by is required")

    async def _run_operation(self, op: OperationRequest) -> str:
        if op.kind == "facts":
            facts = await workflow.execute_activity(
                get_device_facts, FactsRequest(device=self.device), **ACTIVITY_OPTIONS
            )
            return f"EOS {facts.version} on {facts.model}"
        # Microseconds: operations queued in the same second still get their own file.
        timestamp = workflow.now().strftime("%Y%m%dT%H%M%S%fZ")
        return await workflow.execute_activity(
            backup_running_config,
            BackupConfigRequest(device=self.device, timestamp=timestamp),
            **ACTIVITY_OPTIONS,
        )

    @workflow.query
    def recent(self) -> list[OperationResult]:
        return self.recent[-20:]
