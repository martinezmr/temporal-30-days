"""Days 8-12: watch one device forever: signals, queries, updates, and continue-as-new."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.facts import get_device_facts
    from netops_temporal.constants import DEVICE_IO_TASK_QUEUE
    from netops_temporal.models import (
        DeviceFacts,
        FactsRequest,
        SetIntervalRequest,
        WatchRequest,
        WatchStatus,
    )


@workflow.defn
class DeviceWatchWorkflow:
    # @workflow.init: __init__ gets the workflow's input, so state is set up before any
    # handler runs. With update-with-start, the update can run before `run` does.
    @workflow.init
    def __init__(self, req: WatchRequest) -> None:
        # Workflow state is plain attributes. Signals change it; the run loop reacts to it.
        # A continued run starts from the state the previous run handed over (Day 12).
        self.paused = req.paused
        self.check_requested = False
        self.checks = req.checks_so_far
        self.last_facts: DeviceFacts | None = req.last_facts
        self.last_error: str | None = req.last_error
        self.device = req.device
        self.interval_seconds = req.interval_seconds

    @workflow.run
    async def run(self, req: WatchRequest) -> None:
        checks_this_run = 0
        while True:
            # Blocks (durably, for as long as it takes) until nobody has paused us.
            await workflow.wait_condition(lambda: not self.paused)
            try:
                self.last_facts = await workflow.execute_activity(
                    get_device_facts,
                    FactsRequest(device=req.device),
                    task_queue=DEVICE_IO_TASK_QUEUE,  # Day 21: activities run on device-io workers
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                self.checks += 1
                self.last_error = None
            except ActivityError as err:
                # All 3 attempts failed. A watch shouldn't die because the device is down:
                # remember why, and try again at the next interval.
                self.last_error = str(err.cause)
            self.check_requested = False
            try:
                # Sleep until the next check is due, but wake early if someone asks.
                await workflow.wait_condition(
                    lambda: self.check_requested,
                    timeout=timedelta(seconds=self.interval_seconds),
                )
            except TimeoutError:
                pass  # The normal case: the interval passed with no request.

            # Day 12: every pass adds events to history. Before it gets too long, end this run
            # and start a fresh one with the same workflow ID, handing over the state.
            checks_this_run += 1
            if (
                workflow.info().is_continue_as_new_suggested()
                or checks_this_run >= req.max_checks_per_run
            ):
                # Let any signal or update handler that's still running finish first.
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(
                    WatchRequest(
                        device=self.device,
                        interval_seconds=self.interval_seconds,
                        checks_so_far=self.checks,
                        last_facts=self.last_facts,
                        last_error=self.last_error,
                        paused=self.paused,
                        max_checks_per_run=req.max_checks_per_run,
                    )
                )

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

    # A query reads state and returns it. It must not change anything, and it isn't
    # recorded in history.
    @workflow.query
    def status(self) -> WatchStatus:
        return WatchStatus(
            device=self.device,
            paused=self.paused,
            checks=self.checks,
            last_facts=self.last_facts,
            last_error=self.last_error,
            interval_seconds=self.interval_seconds,
        )

    # An update changes state *and* returns a result to the caller, who waits for it.
    @workflow.update
    def set_interval(self, req: SetIntervalRequest) -> WatchStatus:
        # The wait that's already running keeps its timer; the new interval applies from the
        # next one.
        self.interval_seconds = req.interval_seconds
        return self.status()

    # The validator runs first. If it raises, the update is rejected and nothing about it is
    # written to history. It must not change state.
    @set_interval.validator
    def validate_set_interval(self, req: SetIntervalRequest) -> None:
        if not 30 <= req.interval_seconds <= 86400:
            raise ValueError("interval must be 30..86400 seconds")
