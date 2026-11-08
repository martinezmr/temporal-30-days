"""Start one GetFactsWorkflow per device and print the results.

uv run --env-file .env python -m netops_temporal.starters.facts              # all devices
uv run --env-file .env python -m netops_temporal.starters.facts bos-rtr-01   # just one
"""

import asyncio
import sys

from netops_temporal.client import connect
from netops_temporal.constants import DEVICES, ORCHESTRATION_TASK_QUEUE
from netops_temporal.models import FactsRequest
from netops_temporal.workflows.facts import GetFactsWorkflow


async def main(devices: list[str]) -> None:
    client = await connect()
    results = await asyncio.gather(
        *(
            client.execute_workflow(
                GetFactsWorkflow.run,
                FactsRequest(device=device),
                id=f"facts-{device}",
                task_queue=ORCHESTRATION_TASK_QUEUE,
            )
            for device in devices
        ),
        return_exceptions=True,
    )
    for device, result in zip(devices, results, strict=True):
        print(f"{device}: {result}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or DEVICES))
