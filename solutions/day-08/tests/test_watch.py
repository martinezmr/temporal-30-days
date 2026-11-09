"""Day 8: a workflow that runs forever and changes behaviour when it gets a signal."""

import asyncio
import uuid

import pytest
from temporalio.api.enums.v1 import EventType

from netops_temporal.models import WatchRequest
from netops_temporal.workflows.watch import DeviceWatchWorkflow

INTERVAL = 300


async def completed_checks(handle) -> int:
    history = await handle.fetch_history()
    return sum(e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED for e in history.events)


async def wait_for_checks(handle, expected: int) -> None:
    """Poll history (in real time, so no timers are skipped) until `expected` checks are done."""
    for _ in range(100):
        if await completed_checks(handle) >= expected:
            return
        await asyncio.sleep(0.1)
    pytest.fail(f"expected {expected} checks, got {await completed_checks(handle)}")


@pytest.fixture
async def watch(workflow_env, worker):
    handle = await workflow_env.client.start_workflow(
        DeviceWatchWorkflow.run,
        WatchRequest(device="bos-rtr-01", interval_seconds=INTERVAL),
        id=f"watch-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )
    yield handle
    await handle.terminate()


async def test_watch_runs_check_on_start(watch):
    await wait_for_checks(watch, 1)
    assert await completed_checks(watch) == 1


async def test_check_now_signal_triggers_extra_check(watch):
    await wait_for_checks(watch, 1)
    await watch.signal(DeviceWatchWorkflow.check_now)
    await wait_for_checks(watch, 2)


async def test_interval_elapsing_triggers_next_check(workflow_env, watch):
    await wait_for_checks(watch, 1)
    await workflow_env.sleep(INTERVAL + 1)
    await wait_for_checks(watch, 2)


async def test_pause_stops_checks(workflow_env, watch):
    await wait_for_checks(watch, 1)
    await watch.signal(DeviceWatchWorkflow.pause)
    await workflow_env.sleep(INTERVAL * 3)
    assert await completed_checks(watch) == 1
    await watch.signal(DeviceWatchWorkflow.resume)
    await wait_for_checks(watch, 2)
