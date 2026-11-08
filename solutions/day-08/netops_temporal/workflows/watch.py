"""Day 8: watch one device forever, and take orders while running (signals)."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.facts import get_device_facts
    from netops_temporal.models import DeviceFacts, FactsRequest, WatchRequest


@workflow.defn
class DeviceWatchWorkflow:
    def __init__(self) -> None:
        # Workflow state is plain attributes. Signals change it; the run loop reacts to it.
        self.paused = False
        self.check_requested = False
        self.checks = 0
        self.last_facts: DeviceFacts | None = None

    @workflow.run
    async def run(self, req: WatchRequest) -> None:
        while True:
            # Blocks (durably, for as long as it takes) until nobody has paused us.
            await workflow.wait_condition(lambda: not self.paused)
            self.last_facts = await workflow.execute_activity(
                get_device_facts,
                FactsRequest(device=req.device),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            self.checks += 1
            self.check_requested = False
            try:
                # Sleep until the next check is due, but wake early if someone asks.
                await workflow.wait_condition(
                    lambda: self.check_requested,
                    timeout=timedelta(seconds=req.interval_seconds),
                )
            except TimeoutError:
                pass  # The normal case: the interval passed with no request.

    # A signal handler only changes state. It returns nothing and must not block.
    @workflow.signal
    def pause(self) -> None:
        self.paused = True

    @workflow.signal
    def resume(self) -> None:
        self.paused = False

    @workflow.signal
    def check_now(self) -> None:
        self.check_requested = True
