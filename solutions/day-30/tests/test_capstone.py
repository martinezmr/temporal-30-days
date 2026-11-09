"""Day 29: the whole orchestrator, end to end: drift, explanation, approval for risky changes,
remediation through the compliance team's Nexus service, and upgrades as children."""

import asyncio
import uuid

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowUpdateFailedError

from netops_temporal.mock import state as mock_state
from netops_temporal.models import DeviceDecision, OrchestratorInput
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator

DEVICES = ["bos-rtr-01", "bos-acc-01", "nyc-rtr-01", "nyc-acc-01"]


async def eventually(check, tries=300):
    """Poll `check()` (async) until it returns something truthy."""
    for _ in range(tries):
        if result := await check():
            return result
        await asyncio.sleep(0.1)
    raise AssertionError("condition never became true")


async def start(env, worker, devices, **options):
    return await env.client.start_workflow(
        NetworkComplianceOrchestrator.run,
        OrchestratorInput(
            devices=devices,
            dry_run=False,
            approval_risks=["medium", "high"],
            **options,
        ),
        id=f"orchestrator-{uuid.uuid4()}",
        task_queue=worker.task_queue,
    )


async def pending(handle) -> dict:
    return {
        p.device: p for p in await handle.query(NetworkComplianceOrchestrator.pending_approvals)
    }


async def cycles_at_least(handle, n: int) -> bool:
    return await handle.query(NetworkComplianceOrchestrator.cycles) >= n


def nexus_operations(events) -> list[str]:
    return [
        e.nexus_operation_scheduled_event_attributes.operation
        for e in events
        if e.event_type == EventType.EVENT_TYPE_NEXUS_OPERATION_SCHEDULED
    ]


async def test_high_risk_waits_for_approval(nexus_env, nexus_workers):
    # nyc-acc-01 runs the wrong EOS version and misses the NTP line: the model calls it high
    # risk, so its config fix waits for an operator.
    handle = await start(nexus_env, nexus_workers, ["nyc-acc-01"])
    waiting = await eventually(lambda: pending(handle))
    assert waiting["nyc-acc-01"].risk == "high"
    assert waiting["nyc-acc-01"].missing_lines == ["ntp server 192.0.2.10"]
    # Nothing pushed, and the remediation wasn't even asked for yet.
    assert mock_state.applied_lines("nyc-acc-01") == []
    assert nexus_operations((await handle.fetch_history()).events) == ["get_policy"]

    # Only a device that's waiting can be decided on.
    with pytest.raises(WorkflowUpdateFailedError) as err:
        await handle.execute_update(
            NetworkComplianceOrchestrator.decide,
            DeviceDecision(device="bos-acc-01", approve=True, approver="bob"),
        )
    assert "bos-acc-01 isn't waiting for approval" in str(err.value.cause)

    answer = await handle.execute_update(
        NetworkComplianceOrchestrator.decide,
        DeviceDecision(device="nyc-acc-01", approve=True, approver="bob"),
    )
    assert answer == "approved"
    await eventually(lambda: cycles_at_least(handle, 1))
    state = await handle.query(NetworkComplianceOrchestrator.compliance)
    await handle.terminate()
    assert "config: pushed 1 line(s)" in state["nyc-acc-01"].remediation
    assert "upgrade: started upgrade-nyc-acc-01" in state["nyc-acc-01"].remediation
    assert mock_state.applied_lines("nyc-acc-01") == ["ntp server 192.0.2.10"]


async def test_rejected_change_is_not_pushed(nexus_env, nexus_workers):
    handle = await start(nexus_env, nexus_workers, ["bos-acc-01"])
    await eventually(lambda: pending(handle))
    await handle.execute_update(
        NetworkComplianceOrchestrator.decide,
        DeviceDecision(device="bos-acc-01", approve=False, approver="bob"),
    )
    await eventually(lambda: cycles_at_least(handle, 1))
    state = await handle.query(NetworkComplianceOrchestrator.compliance)
    await handle.terminate()
    assert state["bos-acc-01"].remediation == "config: rejected by bob"
    assert mock_state.applied_lines("bos-acc-01") == []


async def test_unanswered_approval_keeps_waiting_next_cycle(nexus_env, nexus_workers):
    # Nobody answers within approval_wait_seconds: the cycle moves on, and the device stays
    # on the list for whoever looks next.
    handle = await start(nexus_env, nexus_workers, ["bos-acc-01"], approval_wait_seconds=1)
    await eventually(lambda: cycles_at_least(handle, 1))
    state = await handle.query(NetworkComplianceOrchestrator.compliance)
    assert state["bos-acc-01"].remediation == "config: waiting for approval (medium risk)"
    assert "bos-acc-01" in await pending(handle)
    # A decision between cycles counts on the next one.
    await handle.execute_update(
        NetworkComplianceOrchestrator.decide,
        DeviceDecision(device="bos-acc-01", approve=True, approver="bob"),
    )
    await handle.signal(NetworkComplianceOrchestrator.force_check)
    await eventually(lambda: cycles_at_least(handle, 2))
    await handle.terminate()
    assert mock_state.applied_lines("bos-acc-01") == ["ntp server 192.0.2.10"]


async def test_full_cycle_converges_config_drift(nexus_env, nexus_workers):
    handle = await start(nexus_env, nexus_workers, DEVICES)

    async def all_waiting():
        waiting = await pending(handle)
        return waiting if set(waiting) == set(DEVICES) else None

    # Every device misses a policy line in the mock lab, so every one waits for a decision.
    for device in await eventually(all_waiting):
        await handle.execute_update(
            NetworkComplianceOrchestrator.decide,
            DeviceDecision(device=device, approve=True, approver="bob"),
        )
    await eventually(lambda: cycles_at_least(handle, 1))

    await handle.signal(NetworkComplianceOrchestrator.force_check)
    await eventually(lambda: cycles_at_least(handle, 2))
    state = await handle.query(NetworkComplianceOrchestrator.compliance)
    still_waiting = await pending(handle)
    await handle.terminate()
    # The second cycle finds no config drift anywhere. nyc-acc-01 still runs the wrong
    # version: its upgrade waits for a maintenance window.
    assert [d for s in state.values() for d in s.drift if d.kind == "config"] == []
    assert [d.kind for d in state["nyc-acc-01"].drift] == ["version"]
    assert still_waiting == {}
