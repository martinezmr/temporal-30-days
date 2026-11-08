"""Days 22-23: the compliance team's worker. Their namespace, their task queue, their Nexus
service, and (Day 23) the remediation workflow behind it, with the activities it needs.

    uv run --env-file .env python -m netops_temporal.workers.compliance

The orchestrator never talks to this worker directly. It calls the Nexus endpoint
`compliance-endpoint`, and the server routes the call here.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from netops_temporal.activities.backup import backup_running_config
from netops_temporal.activities.compliance import check_config_compliance
from netops_temporal.activities.remediation import push_config, rollback_config
from netops_temporal.client import connect
from netops_temporal.constants import (
    COMPLIANCE_NAMESPACE,
    COMPLIANCE_TASK_QUEUE,
    DEVICE_IO_TASK_QUEUE,
)
from netops_temporal.nexus.handler import ComplianceServiceHandler
from netops_temporal.versioning import deployment_config
from netops_temporal.workflows.remediation import ConfigRemediationWorkflow

# What ConfigRemediationWorkflow calls (Day 17's saga).
MAX_ACTIVITIES = 4  # device sessions this worker opens at once

REMEDIATION_ACTIVITIES = [
    backup_running_config,
    push_config,
    check_config_compliance,
    rollback_config,
]


def compliance_worker(client: Client) -> Worker:
    """The Nexus service handler and (Day 23) the remediation workflow, on the task queue the
    endpoint points at."""
    return Worker(
        client,
        task_queue=COMPLIANCE_TASK_QUEUE,
        nexus_service_handlers=[ComplianceServiceHandler()],
        workflows=[ConfigRemediationWorkflow],
        deployment_config=deployment_config(),  # Day 30
    )


def remediation_activity_worker(client: Client, executor: ThreadPoolExecutor) -> Worker:
    """Day 23: the remediation's activities, on the device-io queue (Day 21's split) in this
    namespace."""
    return Worker(
        client,
        task_queue=DEVICE_IO_TASK_QUEUE,
        activities=REMEDIATION_ACTIVITIES,
        activity_executor=executor,
        max_concurrent_activities=MAX_ACTIVITIES,
        deployment_config=deployment_config(),
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await connect(namespace=COMPLIANCE_NAMESPACE)
    with ThreadPoolExecutor(max_workers=MAX_ACTIVITIES) as executor:
        workers = [compliance_worker(client), remediation_activity_worker(client, executor)]
        logging.info(
            "Compliance worker polling %s in %s", COMPLIANCE_TASK_QUEUE, COMPLIANCE_NAMESPACE
        )
        await asyncio.gather(*(w.run() for w in workers))


if __name__ == "__main__":
    asyncio.run(main())
