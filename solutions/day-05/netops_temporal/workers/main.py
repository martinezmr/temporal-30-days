"""Single worker for Weeks 1-3. Register new workflows and activities here as you build them."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio.worker import Worker

from netops_temporal.activities.facts import get_device_facts
from netops_temporal.activities.hello import say_hello
from netops_temporal.activities.show_tech import collect_show_tech
from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE, TEMPORAL_ADDRESS
from netops_temporal.workflows.facts import GetFactsWorkflow
from netops_temporal.workflows.hello import HelloWorkflow
from netops_temporal.workflows.show_tech import ShowTechWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await connect()
    # Sync (`def`) activities run on this thread pool: up to 10 at once. The worker must not
    # accept more activities than that (the SDK default is 100), or the extras wait inside
    # the worker with their timeouts already running.
    with ThreadPoolExecutor(max_workers=10) as executor:
        worker = Worker(
            client,
            task_queue=ORCHESTRATION_TASK_QUEUE,
            workflows=[HelloWorkflow, GetFactsWorkflow, ShowTechWorkflow],
            activities=[say_hello, get_device_facts, collect_show_tech],
            activity_executor=executor,
            max_concurrent_activities=10,
        )
        logging.info("Worker polling %s on %s", ORCHESTRATION_TASK_QUEUE, TEMPORAL_ADDRESS)
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
