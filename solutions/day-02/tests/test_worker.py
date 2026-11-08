"""The worker takes no more activities than its thread pool can run at once."""

from netops_temporal.workers import main as worker_main


class FakeWorker:
    created: dict = {}

    def __init__(self, client, **kwargs):
        FakeWorker.created = kwargs

    async def run(self):
        return None


async def fake_connect():
    return object()


async def test_activity_slots_match_thread_pool(monkeypatch):
    monkeypatch.setattr(worker_main, "Worker", FakeWorker)
    monkeypatch.setattr(worker_main, "connect", fake_connect, raising=False)
    monkeypatch.setattr(worker_main, "Client", type("C", (), {"connect": staticmethod(
        lambda *a, **kw: fake_connect())}), raising=False)
    await worker_main.main()
    kwargs = FakeWorker.created
    assert kwargs["max_concurrent_activities"] == kwargs["activity_executor"]._max_workers
