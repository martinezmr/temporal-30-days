"""Day 16: workflow IDs as locks, and a cap on how many remediations run at once."""

import asyncio
import uuid
from datetime import timedelta

from temporalio.api.enums.v1 import EventType

from netops_temporal.models import OrchestratorInput, RemediationRequest
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator
from netops_temporal.workflows.remediation import ConfigRemediationWorkflow

STARTED = EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED
CLOSED = {
    EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED,
    EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_FAILED,
}


async def start(env, worker, **kwargs):
    return await env.client.start_workflow(
        NetworkComplianceOrchestrator.run,
        OrchestratorInput(**kwargs),
        id=f"orchestrator-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )


async def wait_for_cycles(handle, n: int):
    for _ in range(100):
        if await handle.query(NetworkComplianceOrchestrator.cycles) >= n:
            return await handle.query(NetworkComplianceOrchestrator.compliance)
        await asyncio.sleep(0.1)
    raise AssertionError(f"orchestrator never finished {n} cycle(s)")


def max_open_config_children(history) -> int:
    open_now = peak = 0
    for e in history.events:
        if e.event_type == STARTED:
            if e.start_child_workflow_execution_initiated_event_attributes.workflow_id.startswith(
                "remediate-config-"
            ):
                open_now += 1
                peak = max(peak, open_now)
        elif e.event_type in CLOSED:
            open_now -= 1
    return peak


async def test_no_more_than_two_remediations_at_once(workflow_env, worker):
    handle = await start(workflow_env, worker)
    await wait_for_cycles(handle, 1)
    assert max_open_config_children(await handle.fetch_history()) == 2
    await handle.terminate()


async def test_limit_is_configurable(workflow_env, worker):
    handle = await start(workflow_env, worker, max_parallel_remediations=1)
    await wait_for_cycles(handle, 1)
    assert max_open_config_children(await handle.fetch_history()) == 1
    await handle.terminate()


async def test_duplicate_drift_does_not_start_second_remediation(workflow_env, worker):
    """An operator already has a remediation for bos-acc-01 scheduled. The orchestrator must
    not start a second one: the workflow ID is taken, and it says so."""
    scheduled = await workflow_env.client.start_workflow(
        ConfigRemediationWorkflow.run,
        RemediationRequest(device="bos-acc-01", missing_lines=["ntp server 192.0.2.10"]),
        id="remediate-config-bos-acc-01",
        task_queue=worker.task_queue,
        start_delay=timedelta(hours=1),  # exists (and holds the ID) but hasn't run yet
    )
    handle = await start(workflow_env, worker, devices=["bos-acc-01", "bos-rtr-01"])
    state = await wait_for_cycles(handle, 1)
    assert state["bos-acc-01"].remediation == "config: remediate-config-bos-acc-01 already running"
    assert state["bos-rtr-01"].remediation == "config: dry run, would add 2 line(s)"
    await handle.terminate()
    await scheduled.terminate()
