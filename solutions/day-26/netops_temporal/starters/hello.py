import asyncio
import sys

from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE
from netops_temporal.workflows.hello import HelloWorkflow


async def main(name: str) -> None:
    client = await connect()
    result = await client.execute_workflow(
        HelloWorkflow.run,
        name,
        id=f"hello-{name.lower()}",
        task_queue=ORCHESTRATION_TASK_QUEUE,
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "Temporal"))
