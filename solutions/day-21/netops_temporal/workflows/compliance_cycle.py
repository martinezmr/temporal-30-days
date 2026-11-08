"""Day 18: one compliance check of every device, shared by the orchestrator (Day 14) and the
nightly audit. Plain async functions, called from workflow code: they run inside the calling
workflow, and their activities show up in its history."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.backup import fetch_device_intent
    from netops_temporal.activities.compliance import check_config_compliance
    from netops_temporal.activities.facts import get_device_facts
    from netops_temporal.constants import DEVICE_IO_TASK_QUEUE
    from netops_temporal.drift import compute_drift
    from netops_temporal.models import (
        ComplianceCheckRequest,
        ComplianceState,
        FactsRequest,
        IntentRequest,
    )
    from netops_temporal.policies import POLICIES

ACTIVITY_OPTIONS = {
    # Day 21: every activity runs on the device-io workers.
    "task_queue": DEVICE_IO_TASK_QUEUE,
    "start_to_close_timeout": timedelta(seconds=60),
    "retry_policy": RetryPolicy(maximum_attempts=3),
}


async def collect_compliance(devices: list[str]) -> dict[str, ComplianceState]:
    """Check every device in parallel (Day 7's fan-out)."""
    results = await asyncio.gather(*(check_device(d) for d in devices))
    return {s.device: s for s in results}


async def check_device(device: str) -> ComplianceState:
    """Intent and facts in parallel, then the config check for the device's role.

    An unreachable device becomes `unknown` with the reason: one bad device never stops
    the cycle for the others.
    """
    try:
        intent, facts = await asyncio.gather(
            workflow.execute_activity(
                fetch_device_intent, IntentRequest(device=device), **ACTIVITY_OPTIONS
            ),
            workflow.execute_activity(
                get_device_facts, FactsRequest(device=device), **ACTIVITY_OPTIONS
            ),
        )
        missing = await workflow.execute_activity(
            check_config_compliance,
            ComplianceCheckRequest(device=device, required_lines=POLICIES[intent.role]),
            **ACTIVITY_OPTIONS,
        )
    except ActivityError as err:
        return ComplianceState(
            device=device, status="unknown", checked_at=workflow.now(), error=str(err.cause)
        )
    # Deterministic logic can live in the workflow. Only I/O needs to be an activity.
    drift = compute_drift(intent, facts, missing)
    return ComplianceState(
        device=device,
        status="drifted" if drift else "compliant",
        drift=drift,
        checked_at=workflow.now(),
    )
