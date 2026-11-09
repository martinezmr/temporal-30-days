"""Day 20: find workflows by device, see what they're doing, and measure the worker."""

import asyncio
import socket
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from netops_temporal.constants import DEVICE_IO_TASK_QUEUE
from netops_temporal.models import OrchestratorInput
from netops_temporal.observability import runtime_with_metrics
from netops_temporal.workers.main import ACTIVITIES, WORKFLOWS
from netops_temporal.workflows.hello import HelloWorkflow
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator


async def ids_matching(client: Client, query: str, expected: int = 1) -> set[str]:
    """Visibility is eventually consistent: a just-finished workflow can take a moment to show."""
    for _ in range(100):
        found = {wf.id async for wf in client.list_workflows(query)}
        if len(found) >= expected:
            return found
        await asyncio.sleep(0.1)
    return found


async def run_one_cycle(env, worker, devices):
    handle = await env.client.start_workflow(
        NetworkComplianceOrchestrator.run,
        OrchestratorInput(devices=devices),
        id=f"orchestrator-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )
    for _ in range(100):
        if await handle.query(NetworkComplianceOrchestrator.cycles) >= 1:
            return handle
        await asyncio.sleep(0.1)
    raise AssertionError("no cycle finished")


async def test_remediation_child_has_search_attributes(dev_env, dev_worker):
    handle = await run_one_cycle(dev_env, dev_worker, ["bos-acc-01"])
    await handle.terminate()
    assert await ids_matching(dev_env.client, 'Device="bos-acc-01"') == {
        "remediate-config-bos-acc-01"
    }
    # The child records how it ended: a dry run only plans.
    assert await ids_matching(
        dev_env.client, 'Device="bos-acc-01" AND ComplianceStatus="planned"'
    ) == {"remediate-config-bos-acc-01"}


async def test_remediation_child_has_summary(dev_env, dev_worker):
    handle = await run_one_cycle(dev_env, dev_worker, ["bos-acc-01"])
    await handle.terminate()
    child = await dev_env.client.get_workflow_handle("remediate-config-bos-acc-01").describe()
    assert await child.static_summary() == "config remediation for bos-acc-01 (dry run)"
    assert "ntp server 192.0.2.10" in await child.static_details()


async def test_orchestrator_sets_current_details(workflow_env, worker):
    handle = await run_one_cycle(workflow_env, worker, ["bos-acc-01", "nyc-acc-01"])
    # The same built-in query the UI uses to show "Current Details".
    metadata = await handle.query("__temporal_workflow_metadata")
    details = metadata.current_details
    assert "| bos-acc-01 | drifted |" in details
    assert "cycle 1" in details
    await handle.terminate()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_metrics_endpoint_serves_temporal_metrics(dev_env):
    port = free_port()
    client = await Client.connect(
        dev_env.client.service_client.config.target_host, runtime=runtime_with_metrics(port)
    )
    async with Worker(
        client,
        task_queue=DEVICE_IO_TASK_QUEUE,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
        activity_executor=ThreadPoolExecutor(max_workers=2),
        max_concurrent_activities=2,
    ):
        await client.execute_workflow(
            HelloWorkflow.run,
            "metrics",
            id=f"hello-{uuid.uuid4()}",
            task_queue=DEVICE_IO_TASK_QUEUE,
        )
        body = await asyncio.to_thread(
            lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics").read().decode()
        )
    assert "temporal_workflow_completed" in body
