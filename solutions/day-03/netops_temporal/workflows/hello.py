from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.hello import say_hello


@workflow.defn
class HelloWorkflow:
    """Day 1 smoke test: proves server, worker and client are wired up."""

    @workflow.run
    async def run(self, name: str) -> str:
        return await workflow.execute_activity(
            say_hello,
            name,
            start_to_close_timeout=timedelta(seconds=10),
        )
