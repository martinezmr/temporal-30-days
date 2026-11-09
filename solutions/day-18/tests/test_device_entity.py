"""Day 13: one long-lived workflow per device, the single owner of that device's operations."""

import asyncio
import uuid

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import (
    WithStartWorkflowOperation,
    WorkflowExecutionStatus,
    WorkflowUpdateFailedError,
)
from temporalio.common import WorkflowIDConflictPolicy

from netops_temporal.models import DeviceEntityInput, OperationRequest, OperationResult
from netops_temporal.workflows.device_entity import DeviceEntityWorkflow


async def start_entity(env, worker, max_ops_per_run: int = 200):
    return await env.client.start_workflow(
        DeviceEntityWorkflow.run,
        DeviceEntityInput(device="bos-rtr-01", max_ops_per_run=max_ops_per_run),
        id=f"device-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )


async def test_submit_facts_returns_result(workflow_env, worker):
    handle = await start_entity(workflow_env, worker)
    result = await handle.execute_update(
        DeviceEntityWorkflow.submit, OperationRequest(kind="facts", requested_by="alice")
    )
    assert result == OperationResult(
        kind="facts", requested_by="alice", ok=True, detail="EOS 4.32.0F on cEOSLab"
    )
    await handle.terminate()


async def test_operations_on_same_device_serialize(workflow_env, worker):
    handle = await start_entity(workflow_env, worker)
    results = await asyncio.gather(
        *(
            handle.execute_update(
                DeviceEntityWorkflow.submit, OperationRequest(kind=kind, requested_by=who)
            )
            for kind, who in [("backup", "alice"), ("facts", "bob"), ("backup", "carol")]
        )
    )
    assert all(r.ok for r in results)
    backups = [r.detail for r in results if r.kind == "backup"]
    assert len(set(backups)) == 2  # queued in the same second, still two files
    # One at a time: each activity is scheduled only after the previous one completed.
    history = await handle.fetch_history()
    kinds = {
        EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED: "scheduled",
        EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED: "completed",
    }
    sequence = [kinds[e.event_type] for e in history.events if e.event_type in kinds]
    assert sequence == ["scheduled", "completed"] * 3
    await handle.terminate()


async def test_failed_operation_reported_not_raised(workflow_env, worker, monkeypatch):
    monkeypatch.setenv("MOCK_AUTH_FAIL", "1")
    handle = await start_entity(workflow_env, worker)
    result = await handle.execute_update(
        DeviceEntityWorkflow.submit, OperationRequest(kind="facts", requested_by="alice")
    )
    assert result.ok is False
    assert "auth failed" in result.detail
    await handle.terminate()


async def test_blank_requester_rejected(workflow_env, worker):
    handle = await start_entity(workflow_env, worker)
    with pytest.raises(WorkflowUpdateFailedError):
        await handle.execute_update(
            DeviceEntityWorkflow.submit, OperationRequest(kind="facts", requested_by=" ")
        )
    await handle.terminate()


async def test_recent_query_lists_operations(workflow_env, worker):
    handle = await start_entity(workflow_env, worker)
    for who in ("alice", "bob"):
        await handle.execute_update(
            DeviceEntityWorkflow.submit, OperationRequest(kind="facts", requested_by=who)
        )
    recent = await handle.query(DeviceEntityWorkflow.recent)
    assert [r.requested_by for r in recent] == ["alice", "bob"]
    await handle.terminate()


async def test_update_with_start_creates_entity_once(workflow_env, worker):
    workflow_id = f"device-{uuid.uuid4()}"

    async def submit(who: str) -> OperationResult:
        start_op = WithStartWorkflowOperation(
            DeviceEntityWorkflow.run,
            DeviceEntityInput(device="nyc-acc-01"),
            id=workflow_id,
            task_queue=worker.task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
        return await workflow_env.client.execute_update_with_start_workflow(
            DeviceEntityWorkflow.submit,
            OperationRequest(kind="facts", requested_by=who),
            start_workflow_operation=start_op,
        )

    first, second = await asyncio.gather(submit("alice"), submit("bob"))
    assert first.ok and second.ok
    # One workflow, one run, both operations in its history.
    handle = workflow_env.client.get_workflow_handle(workflow_id)
    history = await handle.fetch_history()
    accepted = EventType.EVENT_TYPE_WORKFLOW_EXECUTION_UPDATE_ACCEPTED
    started = EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED
    assert sum(e.event_type == accepted for e in history.events) == 2
    assert sum(e.event_type == started for e in history.events) == 1
    await handle.terminate()


async def test_entity_handlers_finish_before_can(workflow_env, worker):
    """With room for 1 operation per run, a 2nd queued operation still completes."""
    handle = await start_entity(workflow_env, worker, max_ops_per_run=1)
    results = await asyncio.gather(
        *(
            handle.execute_update(
                DeviceEntityWorkflow.submit, OperationRequest(kind="facts", requested_by=who)
            )
            for who in ("alice", "bob")
        )
    )
    assert [r.ok for r in results] == [True, True]
    first_run = workflow_env.client.get_workflow_handle(handle.id, run_id=handle.result_run_id)
    for _ in range(50):
        if (await first_run.describe()).status == WorkflowExecutionStatus.CONTINUED_AS_NEW:
            break
        await asyncio.sleep(0.1)
    assert (await first_run.describe()).status == WorkflowExecutionStatus.CONTINUED_AS_NEW
    latest = workflow_env.client.get_workflow_handle(handle.id)
    assert (await latest.query(DeviceEntityWorkflow.recent))[-1].requested_by in ("alice", "bob")
    assert len(await latest.query(DeviceEntityWorkflow.recent)) == 2
    await latest.terminate()
