"""Days 8-10: a workflow that runs forever, takes signals, answers queries, accepts updates."""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WithStartWorkflowOperation, WorkflowUpdateFailedError
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.worker import Worker

from netops_temporal.models import SetIntervalRequest, WatchRequest, WatchStatus
from netops_temporal.workers.main import ACTIVITIES, WORKFLOWS
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


async def wait_for_status(env, handle, predicate) -> WatchStatus:
    """Query until `predicate(status)` is true, letting the test server skip retry backoffs."""
    for _ in range(100):
        status = await handle.query(DeviceWatchWorkflow.status)
        if predicate(status):
            return status
        await env.sleep(1)
    pytest.fail(f"condition never met; last status: {status}")


async def test_status_query_reports_checks_and_facts(watch):
    await wait_for_checks(watch, 1)
    status = await watch.query(DeviceWatchWorkflow.status)
    assert status.device == "bos-rtr-01"
    assert status.checks == 1
    assert status.paused is False
    assert status.last_facts.version == "4.32.0F"
    assert status.last_error is None


async def test_status_shows_pause(watch):
    await wait_for_checks(watch, 1)
    await watch.signal(DeviceWatchWorkflow.pause)
    status = await watch.query(DeviceWatchWorkflow.status)
    assert status.paused is True


async def test_unreachable_device_sets_last_error_and_keeps_running(
    workflow_env, watch, monkeypatch
):
    await wait_for_checks(watch, 1)
    monkeypatch.setenv("MOCK_UNREACHABLE", "bos-rtr-01")
    await watch.signal(DeviceWatchWorkflow.check_now)
    status = await wait_for_status(workflow_env, watch, lambda s: s.last_error is not None)
    assert (
        status.last_error == "DeviceUnreachableError: bos-rtr-01 is unreachable (MOCK_UNREACHABLE)"
    )
    assert status.checks == 1  # the failed check doesn't count
    # Still running: the device comes back and the next check succeeds.
    monkeypatch.delenv("MOCK_UNREACHABLE")
    await watch.signal(DeviceWatchWorkflow.check_now)
    status = await wait_for_status(workflow_env, watch, lambda s: s.checks == 2)
    assert status.last_error is None


async def test_query_after_worker_restart_rebuilds_state(workflow_env):
    """A brand-new worker has no memory of the workflow, so answering means replaying it."""
    handle = await workflow_env.client.start_workflow(
        DeviceWatchWorkflow.run,
        WatchRequest(device="nyc-rtr-01", interval_seconds=INTERVAL),
        id=f"watch-{uuid.uuid4()}",
        task_queue="restart-test",
    )
    with ThreadPoolExecutor(max_workers=10) as executor:
        async with Worker(
            workflow_env.client,
            task_queue="restart-test",
            workflows=WORKFLOWS,
            activities=ACTIVITIES,
            activity_executor=executor,
            max_concurrent_activities=10,
            # No workflow cache: the server won't wait for this worker to come back (it
            # would for ~10 s otherwise), and every task really is rebuilt from history.
            max_cached_workflows=0,
        ):
            await wait_for_checks(handle, 1)
            await handle.signal(DeviceWatchWorkflow.check_now)
            await wait_for_checks(handle, 2)
    # The first worker is gone. Queries need a worker, so start a fresh one (workflows only).
    async with Worker(workflow_env.client, task_queue="restart-test", workflows=WORKFLOWS):
        status = await handle.query(DeviceWatchWorkflow.status)
    assert status.checks == 2
    assert status.last_facts.device == "nyc-rtr-01"
    await handle.terminate()


# Day 10: updates, validators, and starting a workflow in the same call.
async def test_set_interval_update_returns_status(watch):
    await wait_for_checks(watch, 1)
    status = await watch.execute_update(
        DeviceWatchWorkflow.set_interval, SetIntervalRequest(interval_seconds=60)
    )
    assert isinstance(status, WatchStatus)
    assert status.interval_seconds == 60


async def test_new_interval_used_for_next_wait(workflow_env, watch):
    await wait_for_checks(watch, 1)
    await watch.execute_update(
        DeviceWatchWorkflow.set_interval, SetIntervalRequest(interval_seconds=60)
    )
    await workflow_env.sleep(INTERVAL + 1)  # the wait already running keeps its old timer
    await wait_for_checks(watch, 2)
    await workflow_env.sleep(61)  # the next wait uses the new interval
    await wait_for_checks(watch, 3)


async def test_invalid_interval_rejected_and_not_in_history(watch):
    await wait_for_checks(watch, 1)
    with pytest.raises(WorkflowUpdateFailedError) as excinfo:
        await watch.execute_update(
            DeviceWatchWorkflow.set_interval, SetIntervalRequest(interval_seconds=5)
        )
    assert "interval must be 30..86400 seconds" in str(excinfo.value.cause)
    history = await watch.fetch_history()
    accepted = EventType.EVENT_TYPE_WORKFLOW_EXECUTION_UPDATE_ACCEPTED
    assert not [e for e in history.events if e.event_type == accepted]


async def test_update_with_start_starts_missing_watch(workflow_env, worker):
    workflow_id = f"watch-{uuid.uuid4()}"
    start_op = WithStartWorkflowOperation(
        DeviceWatchWorkflow.run,
        WatchRequest(device="bos-acc-01"),
        id=workflow_id,
        task_queue=worker.task_queue,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    status = await workflow_env.client.execute_update_with_start_workflow(
        DeviceWatchWorkflow.set_interval,
        SetIntervalRequest(interval_seconds=120),
        start_workflow_operation=start_op,
    )
    assert status.device == "bos-acc-01"
    assert status.interval_seconds == 120
    handle = await start_op.workflow_handle()
    await handle.terminate()


async def test_signal_with_start_starts_missing_watch_or_signals_running_one(workflow_env, worker):
    async def signal_with_start():
        return await workflow_env.client.start_workflow(
            DeviceWatchWorkflow.run,
            WatchRequest(device="nyc-acc-01", interval_seconds=INTERVAL),
            id=workflow_id,
            task_queue=worker.task_queue,
            start_signal="check_now",
        )

    workflow_id = f"watch-{uuid.uuid4()}"
    handle = await signal_with_start()  # not running: starts it (the signal adds nothing new)
    await wait_for_checks(handle, 1)
    await signal_with_start()  # already running: just delivers the signal
    await wait_for_checks(handle, 2)
    await handle.terminate()
