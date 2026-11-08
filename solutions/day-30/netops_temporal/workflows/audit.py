"""Days 18-19: ComplianceAuditWorkflow. Check every device once, return a report, finish.

The orchestrator is a long-running loop with state, so it waits with timers. This audit has no
state between runs: each night stands alone. That's what a Schedule is for (tools/schedules.py).

Day 19: the audit also keeps a config backup of every device as evidence. That changes the
workflow's commands, so the change is behind workflow.patched(): audits that started on the old
code still replay.
"""

import asyncio
from datetime import datetime

from temporalio import workflow
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.backup import backup_running_config
    from netops_temporal.models import AuditReport, AuditRequest, BackupConfigRequest
    from netops_temporal.workflows.compliance_cycle import ACTIVITY_OPTIONS, collect_compliance

# Day 19. The patch ID is permanent once deployed: it's written into every new audit's history.
BACKUP_EVIDENCE = "audit-backup-evidence"


@workflow.defn
class ComplianceAuditWorkflow:
    @workflow.run
    async def run(self, req: AuditRequest) -> AuditReport:
        started_at = workflow.now()
        backups: dict[str, str] = {}
        # New audits: True, and a marker goes into history. Replaying an audit that started
        # before this code existed: False (no marker in its history), so it skips the new step
        # and replays exactly the commands it recorded.
        if workflow.patched(BACKUP_EVIDENCE):
            backups = await backup_evidence(req.devices, started_at)
        # The same check the orchestrator runs each cycle. It only reports: no remediation.
        states = await collect_compliance(req.devices)
        workflow.logger.info("audit: %s", {d: s.status for d, s in sorted(states.items())})
        return AuditReport(started_at=started_at, states=states, backups=backups)


async def backup_evidence(devices: list[str], started_at: datetime) -> dict[str, str]:
    """Back up every device's running config: what it looked like when it was audited."""
    stamp = started_at.strftime("%Y%m%dT%H%M%S%fZ")

    async def one(device: str) -> str:
        try:
            return await workflow.execute_activity(
                backup_running_config,
                BackupConfigRequest(device=device, timestamp=stamp),
                **ACTIVITY_OPTIONS,
            )
        except ActivityError as err:
            return f"backup failed: {err.cause}"  # the check below will report it as unknown

    paths = await asyncio.gather(*(one(d) for d in devices))
    return dict(zip(devices, paths, strict=True))
