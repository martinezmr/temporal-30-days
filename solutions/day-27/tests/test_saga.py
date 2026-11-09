"""Day 17: a config push that undoes itself if anything goes wrong (the saga pattern)."""

import asyncio
import uuid

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import CancelledError
from temporalio.testing import ActivityEnvironment

from netops_temporal.activities.remediation import push_config, rollback_config
from netops_temporal.mock import state as mock_state
from netops_temporal.models import PushRequest, RemediationRequest, RollbackRequest
from netops_temporal.workflows.remediation import ConfigRemediationWorkflow

LINES = ["ntp server 192.0.2.10"]


def activity_types(history) -> list[str]:
    return [
        e.activity_task_scheduled_event_attributes.activity_type.name
        for e in history.events
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
    ]


async def start(env, worker, device="bos-acc-01", lines=LINES):
    return await env.client.start_workflow(
        ConfigRemediationWorkflow.run,
        RemediationRequest(device=device, missing_lines=lines, dry_run=False),
        id=f"remediate-config-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )


def test_push_config_returns_diff_and_applies():
    diff = ActivityEnvironment().run(push_config, PushRequest(device="bos-acc-01", lines=LINES))
    assert diff == "+ntp server 192.0.2.10"
    assert mock_state.applied_lines("bos-acc-01") == LINES


def test_push_of_present_lines_changes_nothing():
    mock_state.apply_lines("bos-acc-01", LINES)
    diff = ActivityEnvironment().run(push_config, PushRequest(device="bos-acc-01", lines=LINES))
    assert diff == ""
    assert mock_state.applied_lines("bos-acc-01") == LINES  # not pushed twice


def test_rollback_config_undoes_last_push():
    ActivityEnvironment().run(push_config, PushRequest(device="bos-acc-01", lines=LINES))
    ActivityEnvironment().run(rollback_config, RollbackRequest(device="bos-acc-01"))
    assert mock_state.applied_lines("bos-acc-01") == []


async def test_push_then_verify_ok_no_rollback(workflow_env, worker):
    handle = await start(workflow_env, worker)
    result = await handle.result()
    assert result.ok is True
    assert result.pushed_lines == LINES
    assert result.diff == "+ntp server 192.0.2.10"
    assert result.rolled_back is False
    assert mock_state.applied_lines("bos-acc-01") == LINES
    assert activity_types(await handle.fetch_history()) == [
        "backup_running_config",
        "push_config",
        "check_config_compliance",
    ]


async def test_verification_failure_rolls_back(workflow_env, worker, monkeypatch):
    monkeypatch.setenv("MOCK_VERIFY_FAIL", "bos-acc-01")
    handle = await start(workflow_env, worker)
    result = await handle.result()
    assert result.ok is False
    assert result.rolled_back is True
    assert "still missing after push" in result.error
    assert mock_state.applied_lines("bos-acc-01") == []
    assert activity_types(await handle.fetch_history()) == [
        "backup_running_config",
        "push_config",
        "check_config_compliance",
        "rollback_config",
    ]


async def test_empty_diff_registers_no_rollback(workflow_env, worker, monkeypatch):
    """Review focus: the lines were already there (someone else's commit). A rollback here
    would undo *their* change, not ours."""
    mock_state.apply_lines("bos-acc-01", LINES)  # an earlier, unrelated commit
    monkeypatch.setenv("MOCK_VERIFY_FAIL", "bos-acc-01")
    result = await (await start(workflow_env, worker)).result()
    assert result.ok is False
    assert result.rolled_back is False
    assert mock_state.applied_lines("bos-acc-01") == LINES  # the earlier commit survives


async def test_unreachable_device_changes_nothing(workflow_env, worker, monkeypatch):
    monkeypatch.setenv("MOCK_UNREACHABLE", "bos-acc-01")
    handle = await start(workflow_env, worker)
    result = await handle.result()  # the test server skips the retry backoffs
    assert result.ok is False
    assert result.rolled_back is False  # nothing was pushed, so there's nothing to undo
    assert "rollback_config" not in activity_types(await handle.fetch_history())


async def test_auth_error_on_push_not_retried(workflow_env, worker, monkeypatch):
    handle = await start(workflow_env, worker)
    monkeypatch.setenv("MOCK_AUTH_FAIL", "1")
    result = await handle.result()
    assert result.ok is False
    history = await handle.fetch_history()
    attempts = [
        e.activity_task_started_event_attributes.attempt
        for e in history.events
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED
    ]
    assert attempts == [1]  # the backup failed on its only attempt; no push was tried


async def test_cancel_after_push_rolls_back(workflow_env, worker, monkeypatch):
    """Review focus: an operator cancels between the push and the verification."""
    monkeypatch.setenv("MOCK_CLI_DELAY", "2")  # every mock config read takes 2 s
    handle = await start(workflow_env, worker)
    for _ in range(100):
        if "check_config_compliance" in activity_types(await handle.fetch_history()):
            break
        await asyncio.sleep(0.1)
    assert mock_state.applied_lines("bos-acc-01") == LINES  # pushed, now verifying
    await handle.cancel()
    with pytest.raises(WorkflowFailureError) as excinfo:
        await handle.result()
    assert isinstance(excinfo.value.cause, CancelledError)
    assert mock_state.applied_lines("bos-acc-01") == []  # rolled back on the way out
    assert activity_types(await handle.fetch_history())[-1] == "rollback_config"
