"""Collect show tech from one device.

uv run --env-file .env python -m netops_temporal.starters.show_tech bos-rtr-01
"""

import asyncio
import sys

from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE
from netops_temporal.models import ShowTechRequest
from netops_temporal.workflows.show_tech import ShowTechWorkflow


async def main(device: str) -> None:
    client = await connect()
    result = await client.execute_workflow(
        ShowTechWorkflow.run,
        ShowTechRequest(device=device),
        id=f"show-tech-{device}",
        task_queue=ORCHESTRATION_TASK_QUEUE,
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "bos-rtr-01"))
