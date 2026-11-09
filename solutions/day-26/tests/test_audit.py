"""Day 18: a one-shot compliance audit that reuses the orchestrator's cycle."""

import asyncio
import uuid

from netops_temporal.models import AuditRequest, OrchestratorInput
from netops_temporal.workflows.audit import ComplianceAuditWorkflow
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator


def summary(states) -> dict:
    """What a check found, without the parts that differ run to run (time, remediation)."""
    return {d: (s.status, [r.model_dump() for r in s.drift], s.error) for d, s in states.items()}


async def test_audit_report_matches_orchestrator_cycle(workflow_env, worker):
    report = await workflow_env.client.execute_workflow(
        ComplianceAuditWorkflow.run,
        AuditRequest(),
        id=f"audit-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )
    orchestrator = await workflow_env.client.start_workflow(
        NetworkComplianceOrchestrator.run,
        OrchestratorInput(),
        id=f"orchestrator-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )
    for _ in range(100):
        if await orchestrator.query(NetworkComplianceOrchestrator.cycles) >= 1:
            break
        await asyncio.sleep(0.1)
    state = await orchestrator.query(NetworkComplianceOrchestrator.compliance)
    await orchestrator.terminate()

    assert summary(report.states) == summary(state)
    assert report.states["nyc-acc-01"].status == "drifted"


async def test_audit_starts_no_remediation(workflow_env, worker):
    """An audit only reports. Fixing things is the orchestrator's job."""
    handle = await workflow_env.client.start_workflow(
        ComplianceAuditWorkflow.run,
        AuditRequest(devices=["bos-acc-01"]),
        id=f"audit-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )
    report = await handle.result()
    assert report.states["bos-acc-01"].remediation is None
    history = await handle.fetch_history()
    assert not any(
        e.HasField("start_child_workflow_execution_initiated_event_attributes")
        for e in history.events
    )
