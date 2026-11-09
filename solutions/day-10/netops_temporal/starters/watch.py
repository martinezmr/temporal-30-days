"""Start a device watch, signal it, query it, or update it.

    uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01            # start
    uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01 pause
    uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01 resume
    uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01 check-now
    uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01 status
    uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01 interval 60

`check-now` and `interval` start the watch first if it isn't running.
"""

import asyncio
import sys

from temporalio.client import Client, WithStartWorkflowOperation
from temporalio.common import WorkflowIDConflictPolicy

from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE
from netops_temporal.models import SetIntervalRequest, WatchRequest
from netops_temporal.workflows.watch import DeviceWatchWorkflow

SIGNALS = {
    "pause": DeviceWatchWorkflow.pause,
    "resume": DeviceWatchWorkflow.resume,
}
ACTIONS = ["start", "status", "check-now", "interval", *SIGNALS]


async def set_interval(client: Client, device: str, seconds: int) -> None:
    # Update-with-start: one call that starts the watch if needed, then runs the update on
    # it and waits for the result. USE_EXISTING means "if it's already running, use that one".
    start_op = WithStartWorkflowOperation(
        DeviceWatchWorkflow.run,
        WatchRequest(device=device),
        id=f"watch-{device}",
        task_queue=ORCHESTRATION_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    status = await client.execute_update_with_start_workflow(
        DeviceWatchWorkflow.set_interval,
        SetIntervalRequest(interval_seconds=seconds),
        start_workflow_operation=start_op,
    )
    print(status.model_dump_json(indent=2))


async def main(device: str, action: str = "start", *args: str) -> None:
    client = await connect()
    workflow_id = f"watch-{device}"
    if action == "start":
        await client.start_workflow(
            DeviceWatchWorkflow.run,
            WatchRequest(device=device),
            id=workflow_id,
            task_queue=ORCHESTRATION_TASK_QUEUE,
        )
        print(f"started {workflow_id}")
    elif action == "status":
        # A query runs on a worker, against the workflow's current state, and returns a value.
        status = await client.get_workflow_handle(workflow_id).query(DeviceWatchWorkflow.status)
        print(status.model_dump_json(indent=2))
    elif action == "check-now":
        # Signal-with-start: signal the watch, starting it first if it isn't running.
        await client.start_workflow(
            DeviceWatchWorkflow.run,
            WatchRequest(device=device),
            id=workflow_id,
            task_queue=ORCHESTRATION_TASK_QUEUE,
            start_signal="check_now",
        )
        print(f"sent check-now to {workflow_id}")
    elif action == "interval":
        await set_interval(client, device, int(args[0]))
    else:
        # A handle is just "the workflow with this ID". Sending a signal doesn't wait for
        # the workflow to do anything: it's written into history, and that's it.
        await client.get_workflow_handle(workflow_id).signal(SIGNALS[action])
        print(f"sent {action} to {workflow_id}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or (len(sys.argv) > 2 and sys.argv[2] not in ACTIONS):
        sys.exit(f"usage: starters.watch <device> [{'|'.join(ACTIONS)}] [seconds]")
    asyncio.run(main(*sys.argv[1:]))
