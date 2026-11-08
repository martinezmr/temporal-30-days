"""Start a device watch, or send it a signal.

uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01            # start
uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01 pause
uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01 resume
uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01 check-now
"""

import asyncio
import sys

from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE
from netops_temporal.models import WatchRequest
from netops_temporal.workflows.watch import DeviceWatchWorkflow

SIGNALS = {
    "pause": DeviceWatchWorkflow.pause,
    "resume": DeviceWatchWorkflow.resume,
    "check-now": DeviceWatchWorkflow.check_now,
}


async def main(device: str, action: str = "start") -> None:
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
    else:
        # A handle is just "the workflow with this ID". Sending a signal doesn't wait for
        # the workflow to do anything: it's written into history, and that's it.
        await client.get_workflow_handle(workflow_id).signal(SIGNALS[action])
        print(f"sent {action} to {workflow_id}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or (len(sys.argv) > 2 and sys.argv[2] not in ("start", *SIGNALS)):
        sys.exit(f"usage: starters.watch <device> [start|{'|'.join(SIGNALS)}]")
    asyncio.run(main(*sys.argv[1:3]))
