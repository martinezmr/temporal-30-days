"""Day 2: get one device's facts, retrying while the device is unreachable."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.facts import get_device_facts


@workflow.defn
class GetFactsWorkflow:
    @workflow.run
    async def run(self, device: str) -> dict:
        return await workflow.execute_activity(
            get_device_facts,
            device,
            # One attempt may take at most 30 s before Temporal gives up on it and retries.
            start_to_close_timeout=timedelta(seconds=30),
            # Wait 2 s, 4 s, 8 s, 16 s between attempts, and stop after the 5th.
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=5,
            ),
        )
