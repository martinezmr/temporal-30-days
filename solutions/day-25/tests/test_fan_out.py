"""Day 16: workflow IDs as locks, and a cap on how many remediations run at once.
(Day 23: remediations are Nexus operations now, not child workflows. Day 25: on a real dev
server, because the time-skipping one leaves some of those operations hanging.)"""

import asyncio
import uuid
from datetime import timedelta

from temporalio.api.enums.v1 import EventType

from netops_temporal.models import OrchestratorInput, RemediationRequest
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator
from netops_temporal.workflows.remediation import ConfigRemediationWorkflow

SCHEDULED = EventType.EVENT_TYPE_NEXUS_OPERATION_SCHEDULED
CLOSED = {
    EventType.EVENT_TYPE_NEXUS_OPERATION_COMPLETED: "nexus_operation_completed_event_attributes",
    EventType.EVENT_TYPE_NEXUS_OPERATION_FAILED: "nexus_operation_failed_event_attributes",
    EventType.EVENT_TYPE_NEXUS_OPERATION_CANCELED: "nexus_operation_canceled_event_attributes",
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
    """The most `remediate` operations in flight at once."""
    remediations: set[int] = set()  # event IDs of scheduled `remediate` operations
    open_now = peak = 0
    for e in history.events:
        if e.event_type == SCHEDULED:
            if e.nexus_operation_scheduled_event_attributes.operation == "remediate":
                remediations.add(e.event_id)
                open_now += 1
                peak = max(peak, open_now)
        elif e.event_type in CLOSED:
            if getattr(e, CLOSED[e.event_type]).scheduled_event_id in remediations:
                open_now -= 1
    return peak


async def test_no_more_than_two_remediations_at_once(dev_env, dev_worker):
    handle = await start(dev_env, dev_worker)
    await wait_for_cycles(handle, 1)
    assert max_open_config_children(await handle.fetch_history()) == 2
    await handle.terminate()


async def test_limit_is_configurable(dev_env, dev_worker):
    handle = await start(dev_env, dev_worker, max_parallel_remediations=1)
    await wait_for_cycles(handle, 1)
    assert max_open_config_children(await handle.fetch_history()) == 1
    await handle.terminate()


async def test_duplicate_drift_does_not_start_second_remediation(dev_env, dev_worker):
    """An operator already has a remediation for bos-acc-01 scheduled. The orchestrator must
    not start a second one: the workflow ID is taken, and it says so."""
    scheduled = await dev_env.client.start_workflow(
        ConfigRemediationWorkflow.run,
        RemediationRequest(device="bos-acc-01", missing_lines=["ntp server 192.0.2.10"]),
        id="remediate-config-bos-acc-01",
        task_queue=dev_worker.task_queue,
        start_delay=timedelta(hours=1),  # exists (and holds the ID) but hasn't run yet
    )
    handle = await start(dev_env, dev_worker, devices=["bos-acc-01", "bos-rtr-01"])
    state = await wait_for_cycles(handle, 1)
    assert state["bos-acc-01"].remediation == "config: remediate-config-bos-acc-01 already running"
    assert state["bos-rtr-01"].remediation == "config: dry run, would add 2 line(s)"
    await handle.terminate()
    await scheduled.terminate()
