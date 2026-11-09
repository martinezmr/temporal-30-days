"""Day 19: changing a workflow that has runs in flight, with workflow.patched()."""

import uuid
from pathlib import Path

import pytest
from temporalio import workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer

from netops_temporal.models import AuditReport, AuditRequest
from netops_temporal.workflows.audit import ComplianceAuditWorkflow, backup_evidence
from netops_temporal.workflows.compliance_cycle import collect_compliance

# An audit recorded by the Day 18 code, before the change.
V1 = Path(__file__).parent / "histories" / "audit_v1.json"


def v1_history() -> WorkflowHistory:
    return WorkflowHistory.from_json("audit-v1", V1.read_text())


@workflow.defn(name="ComplianceAuditWorkflow", sandboxed=False)
class AuditWithoutPatch:
    """The Day 19 change made the wrong way: the new step, with no patched() guard."""

    @workflow.run
    async def run(self, req: AuditRequest) -> AuditReport:
        started_at = workflow.now()
        backups = await backup_evidence(req.devices, started_at)
        states = await collect_compliance(req.devices)
        return AuditReport(started_at=started_at, states=states, backups=backups)


async def test_v1_history_replays_with_patch():
    replayer = Replayer(workflows=[ComplianceAuditWorkflow], data_converter=pydantic_data_converter)
    await replayer.replay_workflow(v1_history())


async def test_v1_history_fails_without_patch():
    replayer = Replayer(workflows=[AuditWithoutPatch], data_converter=pydantic_data_converter)
    with pytest.raises(workflow.NondeterminismError):
        await replayer.replay_workflow(v1_history())


async def test_new_runs_take_patched_path(workflow_env, worker, mock_lab):
    handle = await workflow_env.client.start_workflow(
        ComplianceAuditWorkflow.run,
        AuditRequest(),
        id=f"audit-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )
    report = await handle.result()
    assert set(report.backups) == {"bos-acc-01", "bos-rtr-01", "nyc-acc-01", "nyc-rtr-01"}
    assert all(Path(p).exists() for p in report.backups.values())

    events = (await handle.fetch_history()).events
    # The patch leaves a marker in history, before the new step's commands.
    marker = next(
        i for i, e in enumerate(events) if e.event_type == EventType.EVENT_TYPE_MARKER_RECORDED
    )
    first_activity = next(
        e.activity_task_scheduled_event_attributes.activity_type.name
        for e in events[marker:]
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
    )
    assert first_activity == "backup_running_config"
