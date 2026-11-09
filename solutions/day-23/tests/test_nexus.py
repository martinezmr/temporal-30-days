"""Days 22-23: the compliance team's Nexus service, called from the orchestrator."""

import asyncio
import uuid

from temporalio import workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.exceptions import NexusOperationError
from temporalio.service import RPCError
from temporalio.worker import Worker

from netops_temporal.constants import COMPLIANCE_ENDPOINT, COMPLIANCE_NAMESPACE
from netops_temporal.mock import state as mock_state
from netops_temporal.models import OrchestratorInput, PolicyRequest, RemediationRequest
from netops_temporal.nexus.service import ComplianceService
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator
from netops_temporal.workflows.remediation import ConfigRemediationWorkflow


async def one_cycle(env, worker, devices):
    handle = await env.client.start_workflow(
        NetworkComplianceOrchestrator.run,
        OrchestratorInput(devices=devices),
        id=f"orchestrator-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )
    for _ in range(200):
        if await handle.query(NetworkComplianceOrchestrator.cycles) >= 1:
            return handle
        await asyncio.sleep(0.1)
    raise AssertionError("no cycle finished")


async def test_get_policy_via_nexus(nexus_env, nexus_workers):
    """The orchestrator (namespace default) asks the compliance team's service (namespace
    compliance) for the policy, and gets the same answer POLICIES gave."""
    handle = await one_cycle(nexus_env, nexus_workers, ["bos-rtr-01"])
    state = await handle.query(NetworkComplianceOrchestrator.compliance)
    await handle.terminate()
    assert state["bos-rtr-01"].drift[0].missing_lines == [
        "ntp server 192.0.2.10",
        "logging host 192.0.2.50",
    ]
    events = (await handle.fetch_history()).events
    scheduled = [
        e.nexus_operation_scheduled_event_attributes
        for e in events
        if e.event_type == EventType.EVENT_TYPE_NEXUS_OPERATION_SCHEDULED
    ]
    # (Day 23 adds a `remediate` operation after it.)
    assert [(s.endpoint, s.service, s.operation) for s in scheduled][0] == (
        "compliance-endpoint",
        "ComplianceService",
        "get_policy",
    )
    assert any(e.event_type == EventType.EVENT_TYPE_NEXUS_OPERATION_COMPLETED for e in events)


@workflow.defn(sandboxed=False)
class AskForPolicy:
    """Calls get_policy directly, for one role."""

    @workflow.run
    async def run(self, role: str) -> str:
        compliance = workflow.create_nexus_client(
            service=ComplianceService, endpoint=COMPLIANCE_ENDPOINT
        )
        try:
            policy = await compliance.execute_operation(
                ComplianceService.get_policy, PolicyRequest(role=role)
            )
        except NexusOperationError as err:
            return f"failed: {err.cause}"
        return ", ".join(policy.required_lines)


async def test_unknown_role_fails_without_retry(workflow_env, worker):
    async with Worker(workflow_env.client, task_queue="ask", workflows=[AskForPolicy]):
        assert (
            await workflow_env.client.execute_workflow(
                AskForPolicy.run, "access", id=f"ask-{uuid.uuid4()}", task_queue="ask"
            )
            == "ntp server 192.0.2.10"
        )
        answer = await workflow_env.client.execute_workflow(
            AskForPolicy.run, "firewall", id=f"ask-{uuid.uuid4()}", task_queue="ask"
        )
    # BAD_REQUEST: the handler's error comes straight back, no retries.
    assert answer == "failed: no policy for role 'firewall'"


# Day 23: config remediation is the compliance team's job now, behind their `remediate` operation.


def compliance(env) -> Client:
    return Client(**{**env.client.config(), "namespace": COMPLIANCE_NAMESPACE})


async def wait_for_status(handle, status, tries=200):
    for _ in range(tries):
        try:
            if (await handle.describe()).status == status:
                return
        except RPCError:
            pass  # not started yet
        await asyncio.sleep(0.1)
    raise AssertionError(f"{handle.id} never reached {status}")


async def test_remediate_runs_workflow_in_compliance_namespace(nexus_env, nexus_workers):
    handle = await one_cycle(nexus_env, nexus_workers, ["bos-acc-01"])
    state = await handle.query(NetworkComplianceOrchestrator.compliance)
    await handle.terminate()
    # The result came back through Nexus to the orchestrator.
    assert state["bos-acc-01"].remediation == "config: dry run, would add 1 line(s)"
    # The workflow ran in the compliance team's namespace, not ours.
    remediation = compliance(nexus_env).get_workflow_handle("remediate-config-bos-acc-01")
    assert (await remediation.describe()).status == WorkflowExecutionStatus.COMPLETED
    events = (await handle.fetch_history()).events
    operations = [
        e.nexus_operation_scheduled_event_attributes.operation
        for e in events
        if e.event_type == EventType.EVENT_TYPE_NEXUS_OPERATION_SCHEDULED
    ]
    assert operations == ["get_policy", "remediate"]
    assert not any(
        e.event_type == EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED
        for e in events
    )


async def test_remediation_already_running_fails_operation(nexus_env, nexus_workers):
    # An operator already holds bos-acc-01's lock in the compliance namespace. (Its task queue
    # has no worker, so it stays running for the whole test.)
    held = await compliance(nexus_env).start_workflow(
        ConfigRemediationWorkflow.run,
        RemediationRequest(device="bos-acc-01", missing_lines=["ntp server 10.0.0.1"]),
        id="remediate-config-bos-acc-01",
        task_queue="nobody-polls-this",
    )
    handle = await one_cycle(nexus_env, nexus_workers, ["bos-acc-01"])
    state = await handle.query(NetworkComplianceOrchestrator.compliance)
    await handle.terminate()
    await held.terminate()
    # The handler's operation error came back as the cycle's outcome: no retry, no second run.
    assert state["bos-acc-01"].remediation == "config: remediate-config-bos-acc-01 already running"


async def test_cancel_orchestrator_cancels_nexus_operation(nexus_env, nexus_workers, monkeypatch):
    monkeypatch.setenv("MOCK_CLI_DELAY", "2")  # slow enough to cancel in the middle
    devices = ["bos-acc-01", "bos-rtr-01"]
    handle = await nexus_env.client.start_workflow(
        NetworkComplianceOrchestrator.run,
        # A third config drift waits for one of the two remediation slots (Day 16).
        OrchestratorInput(devices=[*devices, "nyc-rtr-01"], dry_run=False),
        id=f"orchestrator-{uuid.uuid4()}",
        task_queue=nexus_workers.task_queue,
    )
    remediations = [
        compliance(nexus_env).get_workflow_handle(f"remediate-config-{d}") for d in devices
    ]
    for remediation in remediations:
        await wait_for_status(remediation, WorkflowExecutionStatus.RUNNING)
    await handle.cancel()
    # The cancellation crossed the namespace boundary: every remediation was cancelled too,
    # and Day 17's saga undid whatever it had pushed.
    for remediation in remediations:
        await wait_for_status(remediation, WorkflowExecutionStatus.CANCELED)
    for device in devices:
        assert mock_state.applied_lines(device) == []
    # And the orchestrator waited for that before it finished cancelling.
    events = (await handle.fetch_history()).events
    canceled = [
        e.event_id for e in events if e.event_type == EventType.EVENT_TYPE_NEXUS_OPERATION_CANCELED
    ]
    assert len(canceled) == 2
    assert events[-1].event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED
