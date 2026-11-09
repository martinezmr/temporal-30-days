"""Days 22-23: the compliance team's Nexus service, called from the orchestrator."""

import asyncio
import uuid

from temporalio import workflow
from temporalio.api.enums.v1 import EventType
from temporalio.exceptions import NexusOperationError
from temporalio.worker import Worker

from netops_temporal.constants import COMPLIANCE_ENDPOINT
from netops_temporal.models import OrchestratorInput, PolicyRequest
from netops_temporal.nexus.service import ComplianceService
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator


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
    assert [(s.endpoint, s.service, s.operation) for s in scheduled] == [
        ("compliance-endpoint", "ComplianceService", "get_policy")
    ]
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
