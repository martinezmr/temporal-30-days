"""Day 18: the nightly audit schedule."""

import asyncio

from temporalio.client import (
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    WorkflowExecutionStatus,
)

from netops_temporal.models import AuditReport
from netops_temporal.tools.schedules import SCHEDULE_ID, nightly_audit_schedule


def test_schedule_builder_cron_and_overlap():
    schedule = nightly_audit_schedule(hour_utc=3)
    assert schedule.spec.cron_expressions == ["0 3 * * *"]
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert isinstance(schedule.action, ScheduleActionStartWorkflow)
    assert schedule.action.workflow == "ComplianceAuditWorkflow"
    assert schedule.action.id == "audit"


async def test_schedule_trigger_starts_audit(dev_env, dev_worker):
    """On a real dev server: the time-skipping test server doesn't run schedules."""
    handle = await dev_env.client.create_schedule(
        SCHEDULE_ID, nightly_audit_schedule(task_queue=dev_worker.task_queue)
    )
    await handle.trigger()
    for _ in range(100):
        desc = await handle.describe()
        if desc.info.recent_actions:
            break
        await asyncio.sleep(0.1)
    started = desc.info.recent_actions[0].action
    run = dev_env.client.get_workflow_handle(
        started.workflow_id, run_id=started.first_execution_run_id, result_type=AuditReport
    )
    report = await run.result()
    assert set(report.states) == {"bos-acc-01", "bos-rtr-01", "nyc-acc-01", "nyc-rtr-01"}
    assert (await run.describe()).status == WorkflowExecutionStatus.COMPLETED
    # The schedule adds a timestamp to the ID prefix, so every run has its own ID.
    assert started.workflow_id.startswith("audit-")
    await handle.delete()
