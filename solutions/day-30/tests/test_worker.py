"""The all-in-one dev worker: workflows on one queue, activities on the device-io queue, and
no more activities at once than its thread pool can run."""

from netops_temporal.constants import DEVICE_IO_TASK_QUEUE, ORCHESTRATION_TASK_QUEUE
from netops_temporal.workers import main as worker_main


class FakeWorker:
    created: list[dict] = []

    def __init__(self, client, **kwargs):
        FakeWorker.created.append(kwargs)

    async def run(self):
        return None


async def fake_connect(**kwargs):
    return object()


async def test_activity_slots_match_thread_pool(monkeypatch):
    FakeWorker.created = []
    monkeypatch.setattr(worker_main, "Worker", FakeWorker)
    monkeypatch.setattr(worker_main, "connect", fake_connect)
    await worker_main.main()
    by_queue = {kwargs["task_queue"]: kwargs for kwargs in FakeWorker.created}
    assert set(by_queue) == {ORCHESTRATION_TASK_QUEUE, DEVICE_IO_TASK_QUEUE}
    activities = by_queue[DEVICE_IO_TASK_QUEUE]
    assert activities["max_concurrent_activities"] == activities["activity_executor"]._max_workers
    assert "activities" not in by_queue[ORCHESTRATION_TASK_QUEUE]
