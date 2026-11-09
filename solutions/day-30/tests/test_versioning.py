"""Day 30: worker versioning. A new build takes new work; pinned workflows finish on the build
they started on, and auto-upgrade workflows move to the new one."""

import asyncio
import json
import threading
import uuid

from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import VersioningBehavior
from temporalio.contrib.openai_agents.testing import AgentEnvironment, ResponseBuilders, TestModel
from temporalio.converter import DataConverter

from netops_temporal.constants import COMPLIANCE_TASK_QUEUE
from netops_temporal.llm.agent_models import netops_server
from netops_temporal.mock import devices as mock_devices
from netops_temporal.models import (
    Decision,
    OrchestratorInput,
    RemediationRequest,
    TroubleshootRequest,
)
from netops_temporal.versioning import set_current_version
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator
from netops_temporal.workflows.remediation import ConfigRemediationWorkflow
from netops_temporal.workflows.troubleshoot import TroubleshootWorkflow

NTP = "ntp server 192.0.2.10"


async def build_of(handle) -> tuple[str, VersioningBehavior]:
    """The build a workflow last ran on, and how it's versioned."""
    info = (await handle.describe()).raw_description.workflow_execution_info.versioning_info
    return info.deployment_version.build_id, VersioningBehavior(info.behavior)


async def eventually(check, tries=200):
    for _ in range(tries):
        if result := await check():
            return result
        await asyncio.sleep(0.1)
    raise AssertionError("condition never became true")


async def test_workers_unversioned_without_build_id(dev_env, start_workers, monkeypatch):
    monkeypatch.delenv("BUILD_ID", raising=False)
    async with start_workers(dev_env.client):
        handle = await dev_env.client.start_workflow(
            ConfigRemediationWorkflow.run,
            RemediationRequest(device="bos-acc-01", missing_lines=[NTP]),
            id=f"remediate-{uuid.uuid4()}",
            task_queue=COMPLIANCE_TASK_QUEUE,
        )
        await handle.result()
    # Days 1-29 unchanged: no BUILD_ID, no deployment.
    assert (await build_of(handle))[0] == ""


async def test_pinned_remediation_finishes_on_v1(dev_env, start_workers, monkeypatch):
    # The push waits until v2 has taken over, so v2 always arrives in the middle of the saga.
    v2_is_current = threading.Event()
    real_push = mock_devices.push_lines

    def push_after_v2(device, lines):
        assert v2_is_current.wait(30)
        return real_push(device, lines)

    monkeypatch.setattr(mock_devices, "push_lines", push_after_v2)
    client = dev_env.client
    monkeypatch.setenv("BUILD_ID", "v1")
    async with start_workers(client):
        await set_current_version(client, "v1")
        handle = await client.start_workflow(
            ConfigRemediationWorkflow.run,
            RemediationRequest(device="bos-acc-01", missing_lines=[NTP], dry_run=False),
            id=f"remediate-{uuid.uuid4()}",
            task_queue=COMPLIANCE_TASK_QUEUE,
        )

        async def started_on_a_build():
            return (await build_of(handle))[0]

        await eventually(started_on_a_build)
        assert await build_of(handle) == ("v1", VersioningBehavior.PINNED)

        monkeypatch.setenv("BUILD_ID", "v2")
        async with start_workers(client):
            await set_current_version(client, "v2")
            # v2 is current while the v1 remediation is still in the middle of its push.
            assert (await handle.describe()).status == WorkflowExecutionStatus.RUNNING
            v2_is_current.set()
            result = await handle.result()
            later = await client.start_workflow(
                ConfigRemediationWorkflow.run,
                RemediationRequest(device="bos-rtr-01", missing_lines=[NTP]),
                id=f"remediate-{uuid.uuid4()}",
                task_queue=COMPLIANCE_TASK_QUEUE,
            )
            await later.result()

    assert result.ok
    # Pinned: it finished on the build it started on. New work went to v2.
    assert await build_of(handle) == ("v1", VersioningBehavior.PINNED)
    assert await build_of(later) == ("v2", VersioningBehavior.PINNED)


async def test_auto_upgrade_orchestrator_moves_to_v2(dev_env, start_workers, monkeypatch):
    client = dev_env.client
    monkeypatch.setenv("BUILD_ID", "v1")
    async with start_workers(client) as v1:
        await set_current_version(client, "v1")
        handle = await client.start_workflow(
            NetworkComplianceOrchestrator.run,
            OrchestratorInput(devices=["bos-acc-01"]),
            id=f"orchestrator-{uuid.uuid4()}",
            task_queue=v1.task_queue,
        )

        async def cycles(n):
            return await handle.query(NetworkComplianceOrchestrator.cycles) >= n

        await eventually(lambda: cycles(1))
        assert await build_of(handle) == ("v1", VersioningBehavior.AUTO_UPGRADE)

        monkeypatch.setenv("BUILD_ID", "v2")
        async with start_workers(client):
            await set_current_version(client, "v2")
            await handle.signal(NetworkComplianceOrchestrator.force_check)
            await eventually(lambda: cycles(2))
            build = await build_of(handle)
            await handle.terminate()
    # Auto-upgrade: the same, still-running workflow carried on with v2's code.
    assert build == ("v2", VersioningBehavior.AUTO_UPGRADE)


async def test_troubleshoot_waiting_on_a_person_moves_to_v2(dev_env, start_workers, monkeypatch):
    model = TestModel.returning_responses(
        [
            ResponseBuilders.tool_call(
                json.dumps({"lines": [NTP], "rationale": "the policy requires it"}),
                "propose_change",
            ),
            ResponseBuilders.output_message("NTP is missing; I proposed adding it."),
        ]
    )
    async with AgentEnvironment(model=model, mcp_servers={"netops": netops_server}) as agents:
        client = agents.applied_on_client(
            Client(**{**dev_env.client.config(), "data_converter": DataConverter.default})
        )
        monkeypatch.setenv("BUILD_ID", "v1")
        async with start_workers(client) as v1:
            await set_current_version(client, "v1")
            handle = await client.start_workflow(
                TroubleshootWorkflow.run,
                TroubleshootRequest(
                    device="bos-acc-01", symptom="NTP is wrong", requested_by="alice"
                ),
                id=f"troubleshoot-{uuid.uuid4()}",
                task_queue=v1.task_queue,
            )

            async def awaiting_approval():
                return await handle.query(TroubleshootWorkflow.stage) == "awaiting_approval"

            await eventually(awaiting_approval)
            assert await build_of(handle) == ("v1", VersioningBehavior.AUTO_UPGRADE)

            monkeypatch.setenv("BUILD_ID", "v2")
            async with start_workers(client):
                await set_current_version(client, "v2")
                # The approval arrives after the rollout: v1 doesn't have to wait for it.
                await handle.execute_update(
                    TroubleshootWorkflow.decide, Decision(approve=True, approver="bob")
                )
                report = await handle.result()
    assert report.outcome == "approved by bob: pushed 1 line(s)"
    assert await build_of(handle) == ("v2", VersioningBehavior.AUTO_UPGRADE)
