"""Single worker for Weeks 1-3. Register new workflows and activities here as you build them."""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from netops_temporal.activities.hello import say_hello
from netops_temporal.constants import (
    ORCHESTRATION_TASK_QUEUE,
    TEMPORAL_ADDRESS,
    TEMPORAL_NAMESPACE,
)
from netops_temporal.workflows.hello import HelloWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    worker = Worker(
        client,
        task_queue=ORCHESTRATION_TASK_QUEUE,
        workflows=[HelloWorkflow],
        activities=[say_hello],
    )
    logging.info("Worker polling %s on %s", ORCHESTRATION_TASK_QUEUE, TEMPORAL_ADDRESS)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
