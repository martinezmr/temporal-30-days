"""Days 15-17: fix one device's config drift. A child workflow of the orchestrator.

Dry run (Day 15): return the diff it would push. Otherwise (Day 17), a saga: back up, push,
verify, and if anything fails or the workflow is cancelled after the push, roll it back.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.backup import backup_running_config
    from netops_temporal.activities.compliance import check_config_compliance
    from netops_temporal.activities.remediation import push_config, rollback_config
    from netops_temporal.models import (
        BackupConfigRequest,
        ComplianceCheckRequest,
        PushRequest,
        RemediationRequest,
        RemediationResult,
        RollbackRequest,
    )

STEP = {
    "start_to_close_timeout": timedelta(seconds=60),
    "retry_policy": RetryPolicy(maximum_attempts=3),
}
# An undo must try much harder than a step: giving up leaves the device half-changed.
UNDO = {
    "start_to_close_timeout": timedelta(seconds=60),
    "retry_policy": RetryPolicy(maximum_attempts=10),
}


@workflow.defn
class ConfigRemediationWorkflow:
    @workflow.run
    async def run(self, req: RemediationRequest) -> RemediationResult:
        if req.dry_run:
            diff = "\n".join(f"+{line}" for line in req.missing_lines)
            workflow.logger.info("%s: would add %d line(s)", req.device, len(req.missing_lines))
            return RemediationResult(device=req.device, ok=True, diff=diff)

        # The saga: each step that changes the device registers its undo *after* it succeeds.
        compensations: list[Callable[[], Awaitable[None]]] = []
        try:
            stamp = workflow.now().strftime("%Y%m%dT%H%M%S%fZ")
            await workflow.execute_activity(
                backup_running_config,
                BackupConfigRequest(device=req.device, timestamp=stamp),
                **STEP,
            )
            diff = await workflow.execute_activity(
                push_config, PushRequest(device=req.device, lines=req.missing_lines), **STEP
            )
            if diff:
                # Only a push that changed something gets an undo. With an empty diff, the
                # device's last commit is someone else's, and rolling back would undo theirs.
                compensations.append(
                    lambda: workflow.execute_activity(
                        rollback_config, RollbackRequest(device=req.device), **UNDO
                    )
                )
            # The diff is in history now: a permanent record of exactly what changed.
            missing = await workflow.execute_activity(
                check_config_compliance,
                ComplianceCheckRequest(device=req.device, required_lines=req.missing_lines),
                **STEP,
            )
            if missing:
                raise ApplicationError(
                    f"still missing after push: {missing}",
                    type="VerificationFailed",
                    non_retryable=True,
                )
            return RemediationResult(
                device=req.device, ok=True, pushed_lines=req.missing_lines, diff=diff
            )
        except (ActivityError, ApplicationError) as err:
            await self.compensate(compensations)
            if isinstance(err.cause, CancelledError):
                # Cancelled while an activity was running: the cancellation arrives as that
                # activity's error. Undo, then let the cancellation through.
                raise asyncio.CancelledError() from err
            return RemediationResult(
                device=req.device,
                ok=False,
                rolled_back=bool(compensations),
                error=str(err.cause if isinstance(err, ActivityError) else err),
            )
        except asyncio.CancelledError:
            # Cancelled outside an activity (by an operator, or by the orchestrator's
            # REQUEST_CANCEL policy). Undo what was done, then let the cancellation through.
            workflow.logger.warning("%s: cancelled, rolling back", req.device)
            await self.compensate(compensations)
            raise

    async def compensate(self, compensations: list[Callable[[], Awaitable[None]]]) -> None:
        # Undo in reverse order: the last change made is the first one undone.
        for undo in reversed(compensations):
            await undo()
