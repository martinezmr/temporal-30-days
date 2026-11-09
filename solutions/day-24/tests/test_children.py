"""Day 15: the orchestrator starts a child workflow per drift, with a parent close policy each."""

import asyncio
import uuid

from temporalio.api.enums.v1 import EventType, ParentClosePolicy
from temporalio.client import WorkflowExecutionStatus

from netops_temporal.models import OrchestratorInput, RemediationRequest, UpgradeRequest
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator
from netops_temporal.workflows.remediation import ConfigRemediationWorkflow
from netops_temporal.workflows.upgrade import DeviceUpgradeWorkflow

INITIATED = EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED


async def start(env, worker, **kwargs):
    return await env.client.start_workflow(
        NetworkComplianceOrchestrator.run,
        OrchestratorInput(**kwargs),
        id=f"orchestrator-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )


async def children_started(handle) -> dict[str, int]:
    """Child workflow ID -> parent close policy, from the parent's history."""
    history = await handle.fetch_history()
    return {
        e.start_child_workflow_execution_initiated_event_attributes.workflow_id: (
            e.start_child_workflow_execution_initiated_event_attributes.parent_close_policy
        )
        for e in history.events
        if e.event_type == INITIATED
    }


async def wait_for_children(handle, n: int) -> dict[str, int]:
    for _ in range(100):
        children = await children_started(handle)
        if len(children) >= n:
            return children
        await asyncio.sleep(0.1)
    raise AssertionError(f"only {await children_started(handle)} started")


async def test_config_remediation_plans_missing_lines(workflow_env, worker):
    result = await workflow_env.client.execute_workflow(
        ConfigRemediationWorkflow.run,
        RemediationRequest(device="bos-rtr-01", missing_lines=["ntp server 192.0.2.10"]),
        id=f"remediate-config-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )
    assert result.ok is True
    assert result.pushed_lines == []  # dry run: nothing pushed
    assert result.diff == "+ntp server 192.0.2.10"


async def test_upgrade_stand_in_reports_version_unchanged(workflow_env, worker):
    result = await workflow_env.client.execute_workflow(
        DeviceUpgradeWorkflow.run,
        UpgradeRequest(device="nyc-acc-01", target_version="4.33.1F"),
        id=f"upgrade-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )
    assert result.ok is False
    assert "4.32.0F" in result.detail


async def test_drift_starts_one_child_per_device(workflow_env, worker):
    """Day 23: only the upgrade is a child now. Config remediation goes to the compliance
    team's Nexus service (tests/test_nexus.py)."""
    handle = await start(workflow_env, worker)
    children = await wait_for_children(handle, 1)
    assert set(children) == {"upgrade-nyc-acc-01"}
    await handle.terminate()


async def test_child_parent_close_policies(workflow_env, worker):
    handle = await start(workflow_env, worker)
    children = await wait_for_children(handle, 1)
    assert children["upgrade-nyc-acc-01"] == ParentClosePolicy.PARENT_CLOSE_POLICY_ABANDON
    await handle.terminate()


async def test_upgrade_child_survives_parent_termination(dev_env, dev_worker):
    """On a real dev server: the time-skipping server doesn't apply parent close policies."""
    handle = await start(dev_env, dev_worker)
    await wait_for_children(handle, 1)
    await handle.terminate()
    await asyncio.sleep(1)  # give the server a moment to apply the parent close policy
    upgrade = dev_env.client.get_workflow_handle("upgrade-nyc-acc-01")
    # ABANDON: the parent is gone, but the upgrade is still running (in its "reload").
    # With TERMINATE it would have been stopped along with the parent.
    assert (await upgrade.describe()).status == WorkflowExecutionStatus.RUNNING
    await upgrade.terminate()


async def test_state_records_remediation_outcome(workflow_env, worker):
    handle = await start(workflow_env, worker, devices=["bos-acc-01", "nyc-acc-01"])
    for _ in range(100):
        state = await handle.query(NetworkComplianceOrchestrator.compliance)
        if all(s.remediation for s in state.values()) and len(state) == 2:
            break
        await asyncio.sleep(0.1)
    assert state["bos-acc-01"].remediation == "config: dry run, would add 1 line(s)"
    assert state["nyc-acc-01"].remediation == (
        "upgrade: started upgrade-nyc-acc-01; config: dry run, would add 1 line(s)"
    )
    await handle.terminate()
