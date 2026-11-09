"""Day 21: the workflow worker. Workflows only, on the orchestration task queue.

Workflow code never talks to devices, so this worker needs no device credentials and very
little CPU. Run one or two for redundancy.

    uv run --env-file .env python -m netops_temporal.workers.orchestration
"""

import asyncio
import logging

from temporalio.worker import Worker

from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE
from netops_temporal.workers.main import WORKFLOWS, telemetry


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await connect(**telemetry())
    worker = Worker(client, task_queue=ORCHESTRATION_TASK_QUEUE, workflows=WORKFLOWS)
    logging.info("Orchestration worker polling %s", ORCHESTRATION_TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
