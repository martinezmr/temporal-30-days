"""Day 5: collect show tech from one device, surviving worker crashes mid-collection."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ActivityCancellationType

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.show_tech import collect_show_tech
    from netops_temporal.models import ShowTechRequest, ShowTechResult


@workflow.defn
class ShowTechWorkflow:
    @workflow.run
    async def run(self, req: ShowTechRequest) -> ShowTechResult:
        return await workflow.execute_activity(
            collect_show_tech,
            req,
            # The whole collection may take a while...
            start_to_close_timeout=timedelta(minutes=10),
            # ...but if 15 s pass without a heartbeat, this attempt is presumed dead.
            heartbeat_timeout=timedelta(seconds=15),
            retry_policy=RetryPolicy(maximum_attempts=3),
            # On cancel, wait for the activity to clean up before the workflow finishes.
            cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
