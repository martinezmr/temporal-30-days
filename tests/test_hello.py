import uuid

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from netops_temporal.activities.hello import say_hello
from netops_temporal.workflows.hello import HelloWorkflow


async def test_hello_workflow() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client, task_queue="test", workflows=[HelloWorkflow], activities=[say_hello]
        ):
            result = await env.client.execute_workflow(
                HelloWorkflow.run, "Temporal", id=str(uuid.uuid4()), task_queue="test"
            )
    assert result == "Hello, Temporal!"
