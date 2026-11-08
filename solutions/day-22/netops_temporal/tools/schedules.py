"""Day 18: the nightly compliance audit, as a Temporal Schedule (schedule ID "nightly-audit").

uv run --env-file .env python -m netops_temporal.tools.schedules create [hour_utc]
uv run --env-file .env python -m netops_temporal.tools.schedules trigger
uv run --env-file .env python -m netops_temporal.tools.schedules pause "change freeze CHG-1234"
uv run --env-file .env python -m netops_temporal.tools.schedules unpause
uv run --env-file .env python -m netops_temporal.tools.schedules backfill <days> [allow-all]
uv run --env-file .env python -m netops_temporal.tools.schedules delete
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleBackfill,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE
from netops_temporal.models import AuditRequest
from netops_temporal.workflows.audit import ComplianceAuditWorkflow

SCHEDULE_ID = "nightly-audit"


def nightly_audit_schedule(
    hour_utc: int = 2, task_queue: str = ORCHESTRATION_TASK_QUEUE
) -> Schedule:
    """Every night at `hour_utc`:00 UTC, start a ComplianceAuditWorkflow."""
    return Schedule(
        action=ScheduleActionStartWorkflow(
            ComplianceAuditWorkflow.run,
            AuditRequest(),
            # The schedule appends the scheduled time, so each run gets its own ID:
            # audit-2026-11-09T02:00:00Z.
            id="audit",
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(cron_expressions=[f"0 {hour_utc} * * *"]),
        # If last night's audit is somehow still running, don't start another on top of it.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def main(action: str, *args: str) -> None:
    client = await connect()
    handle = client.get_schedule_handle(SCHEDULE_ID)
    if action == "create":
        hour = int(args[0]) if args else 2
        await client.create_schedule(SCHEDULE_ID, nightly_audit_schedule(hour))
        print(f"created {SCHEDULE_ID}: every day at {hour:02d}:00 UTC")
    elif action == "trigger":
        await handle.trigger()  # run it now; the schedule's overlap policy still applies
        print("triggered")
    elif action == "pause":
        await handle.pause(note=args[0] if args else "paused from the CLI")
        print("paused")
    elif action == "unpause":
        await handle.unpause(note="unpaused from the CLI")
        print("unpaused")
    elif action == "backfill":
        # Run the audits that "should have" happened in the last N days (say the worker was
        # down). Each missed run is started now, subject to the overlap policy.
        now = datetime.now(UTC)
        overlap = (
            ScheduleOverlapPolicy.ALLOW_ALL if "allow-all" in args else ScheduleOverlapPolicy.SKIP
        )
        await handle.backfill(
            ScheduleBackfill(
                start_at=now - timedelta(days=int(args[0])), end_at=now, overlap=overlap
            )
        )
        print(f"backfilled {args[0]} day(s) with overlap {overlap.name}")
    elif action == "delete":
        await handle.delete()
        print(f"deleted {SCHEDULE_ID}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(main(*sys.argv[1:]))
