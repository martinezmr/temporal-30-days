"""Day 11: wait for an approval (with a deadline), then for the maintenance window, then act."""

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.backup import backup_running_config
    from netops_temporal.constants import DEVICE_IO_TASK_QUEUE
    from netops_temporal.models import BackupConfigRequest, ChangeWindowRequest, ChangeWindowResult
    from netops_temporal.windows import next_window_start


@workflow.defn
class ChangeWindowWorkflow:
    def __init__(self) -> None:
        self.decision: tuple[bool, str] | None = None  # (approved, who)
        self._stage = "awaiting approval"

    @workflow.run
    async def run(self, req: ChangeWindowRequest) -> ChangeWindowResult:
        # 1. Wait for a human, but not forever. The deadline is a timer on the server, so it
        #    fires on time even if no worker is running at that moment.
        try:
            await workflow.wait_condition(
                lambda: self.decision is not None,
                timeout=timedelta(minutes=req.approval_timeout_minutes),
            )
        except TimeoutError:
            return ChangeWindowResult(
                device=req.device, approved=False, reason="approval timed out"
            )
        approved, who = self.decision
        if not approved:
            return ChangeWindowResult(
                device=req.device, approved=False, reason=f"rejected by {who}"
            )

        # 2. Sleep until the window opens. workflow.now() is the workflow's clock: on replay it
        #    returns the time recorded in history, so this calculation always comes out the same.
        self._stage = "waiting for window"
        wait = next_window_start(workflow.now(), req.window) - workflow.now()
        if wait > timedelta(0):
            await workflow.sleep(wait)

        # 3. The change itself. Here a config backup stands in for it; Week 3 pushes config.
        self._stage = "running"
        ran_at = workflow.now()
        path = await workflow.execute_activity(
            backup_running_config,
            BackupConfigRequest(device=req.device, timestamp=ran_at.strftime("%Y%m%dT%H%M%SZ")),
            task_queue=DEVICE_IO_TASK_QUEUE,  # Day 21: activities run on device-io workers
            start_to_close_timeout=timedelta(seconds=60),
        )
        self._stage = "done"
        return ChangeWindowResult(
            device=req.device,
            approved=True,
            reason=f"approved by {who}",
            ran_at=ran_at,
            backup_path=path,
        )

    @workflow.signal
    def approve(self, approver: str) -> None:
        if self.decision is None:  # the first decision wins
            self.decision = (True, approver)

    @workflow.signal
    def reject(self, approver: str) -> None:
        if self.decision is None:
            self.decision = (False, approver)

    @workflow.query
    def stage(self) -> str:
        return self._stage
