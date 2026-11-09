"""Day 11: durable timers. Wait for an approval (with a deadline), then for a maintenance window."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from temporalio.api.enums.v1 import EventType

from netops_temporal.models import ChangeWindowRequest, MaintenanceWindow
from netops_temporal.windows import next_window_start
from netops_temporal.workflows.change_window import ChangeWindowWorkflow

NIGHT = MaintenanceWindow(start_hour_utc=2, duration_hours=2)  # 02:00-04:00 UTC


def at(hour: int, minute: int = 0, day: int = 10) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


# next_window_start is a pure function: plain unit tests, no Temporal needed.
def test_next_window_later_today():
    assert next_window_start(at(1, 30), NIGHT) == at(2)


def test_next_window_tomorrow_when_past():
    assert next_window_start(at(5), NIGHT) == at(2, day=11)


def test_inside_window_returns_now():
    assert next_window_start(at(3, 15), NIGHT) == at(3, 15)


def test_window_crossing_midnight():
    late = MaintenanceWindow(start_hour_utc=22, duration_hours=4)  # 22:00-02:00 UTC
    assert next_window_start(at(23), late) == at(23)  # inside, before midnight
    assert next_window_start(at(1), late) == at(1)  # inside, after midnight
    assert next_window_start(at(3), late) == at(22)  # after it: tonight's window


async def start(env, worker, approval_timeout_minutes: int = 60):
    return await env.client.start_workflow(
        ChangeWindowWorkflow.run,
        ChangeWindowRequest(
            device="bos-rtr-01", window=NIGHT, approval_timeout_minutes=approval_timeout_minutes
        ),
        id=f"change-window-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )


async def test_approval_timeout_returns_not_approved(workflow_env, worker):
    handle = await start(workflow_env, worker)
    # Waiting for the result lets the test server skip the whole 60-minute deadline at once.
    result = await handle.result()
    assert result.approved is False
    assert result.reason == "approval timed out"
    assert result.ran_at is None


async def test_rejected_returns_not_approved(workflow_env, worker):
    handle = await start(workflow_env, worker)
    await handle.signal(ChangeWindowWorkflow.reject, "alice")
    result = await handle.result()
    assert result.approved is False
    assert result.reason == "rejected by alice"


async def test_approved_waits_for_window_then_runs(workflow_env, worker):
    handle = await start(workflow_env, worker)
    started = (await handle.describe()).start_time
    await handle.signal(ChangeWindowWorkflow.approve, "alice")
    result = await handle.result()
    assert result.approved is True
    assert result.reason == "approved by alice"
    assert result.ran_at >= next_window_start(started, NIGHT)
    assert result.backup_path.endswith(".cfg")
    history = await handle.fetch_history()
    timers = [e for e in history.events if e.event_type == EventType.EVENT_TYPE_TIMER_STARTED]
    assert len(timers) == 2  # the approval deadline, then the wait for the window


async def test_status_query_while_waiting(workflow_env, worker):
    handle = await start(workflow_env, worker)
    await asyncio.sleep(0.5)
    assert await handle.query(ChangeWindowWorkflow.stage) == "awaiting approval"
    await handle.signal(ChangeWindowWorkflow.approve, "alice")
    for _ in range(50):
        if await handle.query(ChangeWindowWorkflow.stage) != "awaiting approval":
            break
        await asyncio.sleep(0.1)
    assert await handle.query(ChangeWindowWorkflow.stage) in ("waiting for window", "done")
    await handle.result()


@pytest.mark.parametrize("hour", [2, 3])
def test_window_start_and_end_boundaries(hour):
    assert next_window_start(at(hour), NIGHT) == at(hour)


def test_window_end_is_exclusive():
    assert next_window_start(at(4), NIGHT) == at(2, day=11)


def test_now_must_be_timezone_aware():
    with pytest.raises(ValueError):
        next_window_start(datetime(2026, 11, 10, 3), NIGHT)


def test_window_hours_validated():
    with pytest.raises(ValueError):
        MaintenanceWindow(start_hour_utc=24, duration_hours=2)
    with pytest.raises(ValueError):
        MaintenanceWindow(start_hour_utc=2, duration_hours=0)


def test_deadline_of_zero_minutes_rejected():
    with pytest.raises(ValueError):
        ChangeWindowRequest(device="bos-rtr-01", window=NIGHT, approval_timeout_minutes=0)
