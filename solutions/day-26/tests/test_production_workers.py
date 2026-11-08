"""Day 21: workflows and device I/O on separate task queues and workers."""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from temporalio.worker import Worker

from netops_temporal.constants import DEVICE_IO_TASK_QUEUE, ORCHESTRATION_TASK_QUEUE
from netops_temporal.models import FactsRequest
from netops_temporal.workers import device_io, orchestration
from netops_temporal.workers.main import ACTIVITIES, WORKFLOWS
from netops_temporal.workflows.facts import GetFactsWorkflow


class FakeWorker:
    created: list[dict] = []

    def __init__(self, client, **kwargs):
        FakeWorker.created.append(kwargs)

    async def run(self):
        return None

    async def shutdown(self):
        return None


async def fake_connect(**kwargs):
    return object()


async def test_activities_route_to_device_io_queue(workflow_env):
    """The orchestration worker has no activities. A workflow's activities wait for the
    device-io worker, and run as soon as one is polling."""
    async with Worker(workflow_env.client, task_queue="orch", workflows=WORKFLOWS):
        handle = await workflow_env.client.start_workflow(
            GetFactsWorkflow.run,
            FactsRequest(device="bos-rtr-01"),
            id=f"facts-{uuid.uuid4()}",
            task_queue="orch",
        )
        await asyncio.sleep(1)
        desc = await handle.describe()
        assert len(desc.raw_description.pending_activities) == 1  # waiting, not failed
        assert desc.raw_description.pending_activities[0].attempt == 1

        with ThreadPoolExecutor(max_workers=2) as pool:
            async with Worker(
                workflow_env.client,
                task_queue=DEVICE_IO_TASK_QUEUE,
                activities=ACTIVITIES,
                activity_executor=pool,
                max_concurrent_activities=2,
            ):
                facts = await handle.result()
    assert facts.facts.device == "bos-rtr-01"


async def test_device_io_worker_settings(monkeypatch):
    FakeWorker.created = []
    monkeypatch.setattr(device_io, "Worker", FakeWorker)
    monkeypatch.setattr(device_io, "connect", fake_connect)
    await device_io.main()
    (kwargs,) = FakeWorker.created
    assert kwargs["task_queue"] == DEVICE_IO_TASK_QUEUE
    assert "workflows" not in kwargs
    assert kwargs["max_task_queue_activities_per_second"] == 5.0
    assert kwargs["graceful_shutdown_timeout"] == timedelta(seconds=30)
    assert kwargs["max_concurrent_activities"] == kwargs["activity_executor"]._max_workers


async def test_orchestration_worker_has_no_activities(monkeypatch):
    FakeWorker.created = []
    monkeypatch.setattr(orchestration, "Worker", FakeWorker)
    monkeypatch.setattr(orchestration, "connect", fake_connect)
    await orchestration.main()
    (kwargs,) = FakeWorker.created
    assert kwargs["task_queue"] == ORCHESTRATION_TASK_QUEUE
    assert kwargs["workflows"] == WORKFLOWS
    assert "activities" not in kwargs
