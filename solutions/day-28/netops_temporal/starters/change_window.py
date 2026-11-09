"""Request a change for one device, then approve or reject it.

uv run --env-file .env python -m netops_temporal.starters.change_window bos-rtr-01 request 2 2
    (window starts 02:00 UTC and lasts 2 hours; optional 5th arg: approval deadline, minutes)
uv run --env-file .env python -m netops_temporal.starters.change_window bos-rtr-01 approve alice
uv run --env-file .env python -m netops_temporal.starters.change_window bos-rtr-01 reject alice
uv run --env-file .env python -m netops_temporal.starters.change_window bos-rtr-01 stage
uv run --env-file .env python -m netops_temporal.starters.change_window bos-rtr-01 result
"""

import asyncio
import sys

from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE
from netops_temporal.models import ChangeWindowRequest, MaintenanceWindow
from netops_temporal.workflows.change_window import ChangeWindowWorkflow


async def main(device: str, action: str, *args: str) -> None:
    client = await connect()
    workflow_id = f"change-window-{device}"
    # get_workflow_handle_for knows the workflow's result type, so result() returns a model.
    handle = client.get_workflow_handle_for(ChangeWindowWorkflow.run, workflow_id)
    if action == "request":
        start_hour, hours, *deadline = (int(a) for a in args)
        req = ChangeWindowRequest(
            device=device,
            window=MaintenanceWindow(start_hour_utc=start_hour, duration_hours=hours),
            approval_timeout_minutes=deadline[0] if deadline else 60,
        )
        await client.start_workflow(
            ChangeWindowWorkflow.run, req, id=workflow_id, task_queue=ORCHESTRATION_TASK_QUEUE
        )
        print(f"started {workflow_id}; waiting for approval")
    elif action in ("approve", "reject"):
        signal = (
            ChangeWindowWorkflow.approve if action == "approve" else ChangeWindowWorkflow.reject
        )
        await handle.signal(signal, args[0])
        print(f"sent {action} from {args[0]}")
    elif action == "stage":
        print(await handle.query(ChangeWindowWorkflow.stage))
    elif action == "result":
        print(await handle.result())


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    asyncio.run(main(*sys.argv[1:]))
