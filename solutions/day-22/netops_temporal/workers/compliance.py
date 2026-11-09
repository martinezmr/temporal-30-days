"""Day 22: the compliance team's worker. Their namespace, their task queue, their Nexus service.

    uv run --env-file .env python -m netops_temporal.workers.compliance

The orchestrator never talks to this worker directly. It calls the Nexus endpoint
`compliance-endpoint`, and the server routes the call here.
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from netops_temporal.client import connect
from netops_temporal.constants import COMPLIANCE_NAMESPACE, COMPLIANCE_TASK_QUEUE
from netops_temporal.nexus.handler import ComplianceServiceHandler


def compliance_worker(client: Client) -> Worker:
    """The Nexus service handler, on the task queue the endpoint points at."""
    return Worker(
        client,
        task_queue=COMPLIANCE_TASK_QUEUE,
        nexus_service_handlers=[ComplianceServiceHandler()],
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await connect(namespace=COMPLIANCE_NAMESPACE)
    worker = compliance_worker(client)
    logging.info("Compliance worker polling %s in %s", COMPLIANCE_TASK_QUEUE, COMPLIANCE_NAMESPACE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
