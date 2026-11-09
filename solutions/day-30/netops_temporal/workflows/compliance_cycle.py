"""Days 18-22: one compliance check of every device, shared by the orchestrator (Day 14) and the
nightly audit. Plain async functions, called from workflow code: they run inside the calling
workflow, and their activities show up in its history."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, NexusOperationError

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.backup import fetch_device_intent
    from netops_temporal.activities.compliance import check_config_compliance
    from netops_temporal.activities.facts import get_device_facts
    from netops_temporal.constants import COMPLIANCE_ENDPOINT, DEVICE_IO_TASK_QUEUE
    from netops_temporal.drift import compute_drift
    from netops_temporal.models import (
        ComplianceCheckRequest,
        ComplianceState,
        FactsRequest,
        IntentRequest,
        PolicyRequest,
    )
    from netops_temporal.nexus.service import ComplianceService
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
        required_lines = await policy_for(intent.role)
        missing = await workflow.execute_activity(
            check_config_compliance,
            ComplianceCheckRequest(device=device, required_lines=required_lines),
            **ACTIVITY_OPTIONS,
        )
    except (ActivityError, NexusOperationError) as err:
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


async def policy_for(role: str) -> list[str]:
    """Day 22: the compliance team owns the policy now, behind their Nexus service."""
    # A Nexus operation is a new command. Orchestrators and audits that started before this
    # change have no Nexus events in their history, so they keep reading POLICIES (Day 19).
    if not workflow.patched("policy-from-nexus"):
        return POLICIES[role]
    compliance = workflow.create_nexus_client(
        service=ComplianceService, endpoint=COMPLIANCE_ENDPOINT
    )
    policy = await compliance.execute_operation(
        ComplianceService.get_policy, PolicyRequest(role=role)
    )
    return policy.required_lines
