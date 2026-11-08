"""Day 7: back up every device in parallel and pair each backup with its intent."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.backup import backup_running_config, fetch_device_intent
    from netops_temporal.constants import DEVICE_IO_TASK_QUEUE
    from netops_temporal.models import (
        BackupConfigRequest,
        BackupReport,
        BackupRequest,
        DeviceBackupResult,
        IntentRequest,
    )

ACTIVITY_OPTIONS = {
    # Day 21: every activity runs on the device-io workers.
    "task_queue": DEVICE_IO_TASK_QUEUE,
    "start_to_close_timeout": timedelta(seconds=60),
    "retry_policy": RetryPolicy(maximum_attempts=3),
}


@workflow.defn
class ConfigBackupWorkflow:
    @workflow.run
    async def run(self, req: BackupRequest) -> BackupReport:
        started_at = workflow.now()
        # One timestamp for the whole run, from workflow time (Day 4), so every file name
        # is the same on replay.
        timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
        # Start every device at once. gather() is safe in a workflow: it only schedules
        # activities; they run in parallel on the workers' thread pools.
        results = await asyncio.gather(
            *(self.backup_one(device, timestamp) for device in req.devices)
        )
        workflow.logger.info("Backed up %d of %d devices", sum(r.ok for r in results), len(results))
        return BackupReport(started_at=started_at, results=list(results))

    async def backup_one(self, device: str, timestamp: str) -> DeviceBackupResult:
        """Backup and intent for one device, run side by side. Failures become data."""
        backup, intent = await asyncio.gather(
            workflow.execute_activity(
                backup_running_config,
                BackupConfigRequest(device=device, timestamp=timestamp),
                **ACTIVITY_OPTIONS,
            ),
            workflow.execute_activity(
                fetch_device_intent, IntentRequest(device=device), **ACTIVITY_OPTIONS
            ),
            return_exceptions=True,
        )
        errors = []
        for outcome in (backup, intent):
            if isinstance(outcome, ActivityError):
                errors.append(str(outcome.cause))
            elif isinstance(outcome, BaseException):
                raise outcome  # a bug or a cancellation, not a device problem: don't hide it
        return DeviceBackupResult(
            device=device,
            ok=not errors,
            backup_path=None if isinstance(backup, BaseException) else backup,
            intent=None if isinstance(intent, BaseException) else intent,
            error="; ".join(errors) or None,
        )
