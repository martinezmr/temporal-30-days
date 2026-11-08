"""Days 26-27: ask the troubleshooting agent about a device, and decide on what it proposes.

uv run --env-file .env python -m netops_temporal.starters.troubleshoot ask bos-acc-01 \
    "users on Et1 can't connect" --as alice
uv run --env-file .env python -m netops_temporal.starters.troubleshoot approve <id> --as bob
uv run --env-file .env python -m netops_temporal.starters.troubleshoot reject <id> --as bob
uv run --env-file .env python -m netops_temporal.starters.troubleshoot report <id>
"""

import asyncio
import getpass
import sys
import uuid

from temporalio.client import WorkflowUpdateFailedError
from temporalio.service import RPCError

from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE
from netops_temporal.models import Decision, TroubleshootReport, TroubleshootRequest
from netops_temporal.workflows.troubleshoot import TroubleshootWorkflow


def option(args: list[str], name: str) -> str | None:
    """The value after `name` in args, if it's there."""
    return args[args.index(name) + 1] if name in args[:-1] else None


def show(report: TroubleshootReport) -> None:
    print(f"\n{report.device}: {report.findings}")
    if report.proposed_change:
        print("\nProposed change:")
        for line in report.proposed_change.lines:
            print(f"  {line}")
        print(f"because: {report.proposed_change.rationale}")
    print(f"\noutcome: {report.outcome}")


async def main(action: str, *args: str) -> None:
    client = await connect()
    who = option(list(args), "--as") or getpass.getuser()
    if action == "ask":
        device, symptom = args[0], args[1]
        workflow_id = f"troubleshoot-{device}-{uuid.uuid4().hex[:6]}"
        handle = await client.start_workflow(
            TroubleshootWorkflow.run,
            TroubleshootRequest(device=device, symptom=symptom, requested_by=who),
            id=workflow_id,
            task_queue=ORCHESTRATION_TASK_QUEUE,
        )
        print(f"started {workflow_id}, investigating...")
        # Day 27: the workflow doesn't end when the agent does: wait for the agent, not for it.
        while (stage := await handle.query(TroubleshootWorkflow.stage)) == "investigating":
            await asyncio.sleep(1)
        if stage == "awaiting_approval":
            proposal = await handle.query(TroubleshootWorkflow.proposal)
            print("\nProposed change, waiting for someone else's approval:")
            for line in proposal.lines:
                print(f"  {line}")
            print(f"because: {proposal.rationale}")
            print(f"\napprove or reject {workflow_id} (as someone other than {who})")
        else:
            show(await handle.result())
    elif action in ("approve", "reject"):
        handle = client.get_workflow_handle_for(TroubleshootWorkflow.run, args[0])
        comment = option(list(args), "--comment") or ""
        try:
            answer = await handle.execute_update(
                TroubleshootWorkflow.decide,
                Decision(approve=action == "approve", approver=who, comment=comment),
            )
        except WorkflowUpdateFailedError as err:  # the validator said no
            sys.exit(f"decision refused: {err.cause}")
        except RPCError as err:  # e.g. the workflow already finished
            sys.exit(f"decision refused: {err}")
        print(f"{answer} by {who}")
        show(await handle.result())
    elif action == "report":
        show(await client.get_workflow_handle_for(TroubleshootWorkflow.run, args[0]).result())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    asyncio.run(main(*sys.argv[1:]))
