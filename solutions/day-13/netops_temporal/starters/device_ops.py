"""Ask a device's entity workflow to do something, starting the entity if needed.

uv run --env-file .env python -m netops_temporal.starters.device_ops bos-rtr-01 facts alice
uv run --env-file .env python -m netops_temporal.starters.device_ops bos-rtr-01 backup bob 5
    (5 backups submitted at the same moment: watch them run one at a time)
uv run --env-file .env python -m netops_temporal.starters.device_ops bos-rtr-01 recent
"""

import asyncio
import sys

from temporalio.client import Client, WithStartWorkflowOperation
from temporalio.common import WorkflowIDConflictPolicy

from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE
from netops_temporal.models import DeviceEntityInput, OperationRequest, OperationResult
from netops_temporal.workflows.device_entity import DeviceEntityWorkflow


async def submit(client: Client, device: str, op: OperationRequest) -> OperationResult:
    # Update-with-start (Day 10): the first operation on a device creates its entity.
    start_op = WithStartWorkflowOperation(
        DeviceEntityWorkflow.run,
        DeviceEntityInput(device=device),
        id=f"device-{device}",
        task_queue=ORCHESTRATION_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    return await client.execute_update_with_start_workflow(
        DeviceEntityWorkflow.submit, op, start_workflow_operation=start_op
    )


async def main(device: str, kind: str, requested_by: str = "", count: str = "1") -> None:
    client = await connect()
    if kind == "recent":
        handle = client.get_workflow_handle(f"device-{device}")
        for result in await handle.query(DeviceEntityWorkflow.recent):
            print(result)
        return
    op = OperationRequest(kind=kind, requested_by=requested_by)
    results = await asyncio.gather(*(submit(client, device, op) for _ in range(int(count))))
    for result in results:
        print(result)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    asyncio.run(main(*sys.argv[1:]))
