import uuid

from netops_temporal.workflows.hello import HelloWorkflow


async def test_hello_workflow(workflow_env, worker) -> None:
    result = await workflow_env.client.execute_workflow(
        HelloWorkflow.run, "Temporal", id=str(uuid.uuid4()), task_queue=worker.task_queue
    )
    assert result == "Hello, Temporal!"
