"""Day 14: NetworkComplianceOrchestrator v0 detects drift and reports it. No remediation yet."""

import asyncio
import uuid

import pytest
from temporalio.testing import ActivityEnvironment

from netops_temporal.activities.compliance import check_config_compliance
from netops_temporal.models import ComplianceCheckRequest, OrchestratorInput, SetIntervalRequest
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator


def test_check_config_compliance_returns_missing_lines():
    missing = ActivityEnvironment().run(
        check_config_compliance,
        ComplianceCheckRequest(
            device="bos-rtr-01", required_lines=["hostname bos-rtr-01", "ntp server 192.0.2.10"]
        ),
    )
    assert missing == ["ntp server 192.0.2.10"]


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
    pytest.fail(f"orchestrator never finished {n} cycle(s)")


async def test_orchestrator_first_cycle_reports_expected_drift(workflow_env, worker):
    handle = await start(workflow_env, worker)
    state = await wait_for_cycles(handle, 1)
    assert set(state) == {"bos-rtr-01", "bos-acc-01", "nyc-rtr-01", "nyc-acc-01"}
    assert all(s.status == "drifted" for s in state.values())
    assert [d.kind for d in state["nyc-acc-01"].drift] == ["version", "config"]
    for device in ("bos-rtr-01", "bos-acc-01", "nyc-rtr-01"):
        assert [d.kind for d in state[device].drift] == ["config"]
    assert state["bos-rtr-01"].drift[0].missing_lines == [
        "ntp server 192.0.2.10",
        "logging host 192.0.2.50",
    ]
    await handle.terminate()


async def test_unreachable_device_is_unknown_not_fatal(workflow_env, worker, monkeypatch):
    monkeypatch.setenv("MOCK_UNREACHABLE", "nyc-rtr-01")
    handle = await start(workflow_env, worker)
    task = asyncio.create_task(wait_for_cycles(handle, 1))
    # Let the test server skip the activity retry backoff.
    while not task.done():
        await workflow_env.sleep(5)
    state = task.result()
    assert state["nyc-rtr-01"].status == "unknown"
    assert "unreachable" in state["nyc-rtr-01"].error
    assert state["bos-rtr-01"].status == "drifted"
    await handle.terminate()


async def test_compliant_device_reported_compliant(workflow_env, worker):
    from netops_temporal.mock import state as mock_state

    mock_state.apply_lines("bos-acc-01", ["ntp server 192.0.2.10"])
    handle = await start(workflow_env, worker, devices=["bos-acc-01"])
    state = await wait_for_cycles(handle, 1)
    assert state["bos-acc-01"].status == "compliant"
    assert state["bos-acc-01"].drift == []
    await handle.terminate()


# Day 23: from the second cycle on, remediations reuse their workflow IDs through Nexus, which
# the time-skipping test server doesn't handle (the operations never complete). These two run
# on a real dev server instead.
async def test_force_check_runs_another_cycle(dev_env, dev_worker):
    handle = await start(dev_env, dev_worker)
    await wait_for_cycles(handle, 1)
    await handle.signal(NetworkComplianceOrchestrator.force_check)
    await wait_for_cycles(handle, 2)
    await handle.terminate()


async def test_interval_elapsing_runs_next_cycle(dev_env, dev_worker):
    # No time skipping on a real server, so a short interval. (The input isn't validated like
    # the set_interval update is.)
    handle = await start(dev_env, dev_worker, interval_seconds=2)
    await wait_for_cycles(handle, 1)
    await asyncio.sleep(3)
    await wait_for_cycles(handle, 2)
    await handle.terminate()


async def test_set_interval_validated(dev_env, dev_worker):
    from temporalio.client import WorkflowUpdateFailedError

    # Day 28: on a real dev server, like test_continue_as_new_carries_state below: the
    # time-skipping server sometimes leaves one of the cycle's Nexus operations hanging.
    handle = await start(dev_env, dev_worker)
    await wait_for_cycles(handle, 1)
    assert (
        await handle.execute_update(
            NetworkComplianceOrchestrator.set_interval, SetIntervalRequest(interval_seconds=60)
        )
        == 60
    )
    with pytest.raises(WorkflowUpdateFailedError):
        await handle.execute_update(
            NetworkComplianceOrchestrator.set_interval, SetIntervalRequest(interval_seconds=5)
        )
    await handle.terminate()


async def test_continue_as_new_carries_state(dev_env, dev_worker):
    # Day 25: on a real dev server with a short interval. With every cycle's Nexus operations,
    # the time-skipping server sometimes leaves one hanging (see test_fan_out.py).
    handle = await start(dev_env, dev_worker, interval_seconds=2, max_cycles_per_run=1)
    await wait_for_cycles(handle, 1)
    latest = dev_env.client.get_workflow_handle(handle.id)
    for _ in range(100):
        await asyncio.sleep(0.1)
        if await latest.query(NetworkComplianceOrchestrator.cycles) >= 2:
            break
    assert await latest.query(NetworkComplianceOrchestrator.cycles) >= 2
    state = await latest.query(NetworkComplianceOrchestrator.compliance)
    assert len(state) == 4
    assert (await latest.describe()).run_id != handle.result_run_id
    await latest.terminate()
