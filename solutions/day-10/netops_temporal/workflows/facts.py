"""Day 2-4: get one device's facts, retrying while the device is unreachable."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.facts import get_device_facts
    from netops_temporal.models import FactsReport, FactsRequest


@workflow.defn
class GetFactsWorkflow:
    @workflow.run
    async def run(self, req: FactsRequest) -> FactsReport:
        facts = await workflow.execute_activity(
            get_device_facts,
            req,
            # One attempt may take at most 30 s before Temporal gives up on it and retries.
            start_to_close_timeout=timedelta(seconds=30),
            # Wait 2 s, 4 s, 8 s, 16 s between attempts, and stop after the 5th.
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=5,
            ),
        )
        # workflow.logger skips lines while the workflow is replaying, so this logs once.
        workflow.logger.info("%s runs EOS %s", facts.device, facts.version)
        # workflow.now(), not datetime.now(): on replay it returns the same time as the
        # first run, because it comes from the event history.
        return FactsReport(facts=facts, collected_at=workflow.now())
