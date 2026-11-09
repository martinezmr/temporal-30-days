"""Day 26: ask the troubleshooting agent about a device, and wait for its report.

uv run --env-file .env python -m netops_temporal.starters.troubleshoot bos-acc-01 \
    "users on Et1 can't connect"
"""

import asyncio
import sys
import uuid

from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE
from netops_temporal.models import TroubleshootRequest
from netops_temporal.workflows.troubleshoot import TroubleshootWorkflow


async def main(device: str, symptom: str) -> None:
    client = await connect()
    workflow_id = f"troubleshoot-{device}-{uuid.uuid4().hex[:6]}"
    print(f"started {workflow_id}; follow it in the UI")
    report = await client.execute_workflow(
        TroubleshootWorkflow.run,
        TroubleshootRequest(device=device, symptom=symptom),
        id=workflow_id,
        task_queue=ORCHESTRATION_TASK_QUEUE,
    )
    print(f"\n{report.device}: {report.findings}")
    if report.proposed_change:
        print("\nProposed change (not applied):")
        for line in report.proposed_change.lines:
            print(f"  {line}")
        print(f"because: {report.proposed_change.rationale}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
