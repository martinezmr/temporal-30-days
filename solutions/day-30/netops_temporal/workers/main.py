"""The all-in-one development worker: every workflow and every activity, in one process.

Day 21 splits them for production: workers/orchestration.py runs the workflows and
workers/device_io.py runs the activities, each on its own task queue. This file runs both
queues at once, so day-to-day development still needs only one terminal. Register new workflows
and activities in the lists below.
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from temporalio.worker import Worker

from netops_temporal.activities.backup import backup_running_config, fetch_device_intent
from netops_temporal.activities.compliance import check_config_compliance
from netops_temporal.activities.explain import explain_drift
from netops_temporal.activities.facts import get_device_facts
from netops_temporal.activities.hello import say_hello
from netops_temporal.activities.remediation import push_config, rollback_config
from netops_temporal.activities.show import show_command
from netops_temporal.activities.show_tech import collect_show_tech
from netops_temporal.client import connect
from netops_temporal.constants import (
    DEVICE_IO_TASK_QUEUE,
    ORCHESTRATION_TASK_QUEUE,
    TEMPORAL_ADDRESS,
)
from netops_temporal.observability import runtime_with_metrics, tracing_interceptor
from netops_temporal.versioning import deployment_config
from netops_temporal.workflows.audit import ComplianceAuditWorkflow
from netops_temporal.workflows.backup import ConfigBackupWorkflow
from netops_temporal.workflows.change_window import ChangeWindowWorkflow
from netops_temporal.workflows.device_entity import DeviceEntityWorkflow
from netops_temporal.workflows.facts import GetFactsWorkflow
from netops_temporal.workflows.hello import HelloWorkflow
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator
from netops_temporal.workflows.remediation import ConfigRemediationWorkflow
from netops_temporal.workflows.show_tech import ShowTechWorkflow
from netops_temporal.workflows.troubleshoot import TroubleshootWorkflow
from netops_temporal.workflows.upgrade import DeviceUpgradeWorkflow
from netops_temporal.workflows.watch import DeviceWatchWorkflow

# One list of everything this worker runs. Tests and replay import these too, so a test
# worker can never drift from the real one.
WORKFLOWS = [
    HelloWorkflow,
    GetFactsWorkflow,
    ShowTechWorkflow,
    ConfigBackupWorkflow,
    DeviceWatchWorkflow,
    ChangeWindowWorkflow,
    DeviceEntityWorkflow,
    NetworkComplianceOrchestrator,
    ConfigRemediationWorkflow,
    DeviceUpgradeWorkflow,
    ComplianceAuditWorkflow,
    TroubleshootWorkflow,  # Day 26
]
ACTIVITIES = [
    say_hello,
    get_device_facts,
    collect_show_tech,
    backup_running_config,
    fetch_device_intent,
    check_config_compliance,
    push_config,
    rollback_config,
    explain_drift,  # Day 25
    show_command,  # Day 26: the agent's CLI tool (from Day 28 it uses the MCP server)
]


def telemetry() -> dict:
    """Day 20: METRICS_PORT=9464 serves Prometheus metrics; OTEL_CONSOLE=1 prints trace spans."""
    port = os.environ.get("METRICS_PORT")
    if port:
        logging.info("Metrics on http://localhost:%s/metrics", port)
    return {
        "runtime": runtime_with_metrics(int(port)) if port else None,
        "interceptors": [tracing_interceptor()] if os.environ.get("OTEL_CONSOLE") == "1" else [],
    }


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await connect(**telemetry())
    # Sync (`def`) activities run on this thread pool: up to 10 at once. The worker must not
    # accept more activities than that (the SDK default is 100), or the extras wait inside
    # the worker with their timeouts already running.
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Day 30: with BUILD_ID set, both workers join the "netops" deployment as that build.
        workflow_worker = Worker(
            client,
            task_queue=ORCHESTRATION_TASK_QUEUE,
            workflows=WORKFLOWS,
            deployment_config=deployment_config(),
        )
        # Day 21: workflows send their activities to the device-io queue.
        activity_worker = Worker(
            client,
            task_queue=DEVICE_IO_TASK_QUEUE,
            activities=ACTIVITIES,
            activity_executor=executor,
            max_concurrent_activities=10,
            deployment_config=deployment_config(),
        )
        logging.info(
            "Worker polling %s and %s on %s",
            ORCHESTRATION_TASK_QUEUE,
            DEVICE_IO_TASK_QUEUE,
            TEMPORAL_ADDRESS,
        )
        await asyncio.gather(workflow_worker.run(), activity_worker.run())


if __name__ == "__main__":
    asyncio.run(main())
