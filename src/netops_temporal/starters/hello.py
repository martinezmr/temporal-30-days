import asyncio
import sys

from temporalio.client import Client

from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE, TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE
from netops_temporal.workflows.hello import HelloWorkflow


async def main(name: str) -> None:
    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    result = await client.execute_workflow(
        HelloWorkflow.run,
        name,
        id=f"hello-{name.lower()}",
        task_queue=ORCHESTRATION_TASK_QUEUE,
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "Temporal"))
