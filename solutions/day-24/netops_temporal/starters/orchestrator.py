"""Run and talk to the compliance orchestrator (there's one, with workflow ID "orchestrator").

uv run --env-file .env python -m netops_temporal.starters.orchestrator start
uv run --env-file .env python -m netops_temporal.starters.orchestrator start --apply
uv run --env-file .env python -m netops_temporal.starters.orchestrator start --apply --ticket CHG42
uv run --env-file .env python -m netops_temporal.starters.orchestrator status
uv run --env-file .env python -m netops_temporal.starters.orchestrator force-check
uv run --env-file .env python -m netops_temporal.starters.orchestrator interval 300
"""

import asyncio
import sys

from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE
from netops_temporal.models import OrchestratorInput, SetIntervalRequest
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator

WORKFLOW_ID = "orchestrator"


def option(args: tuple[str, ...], name: str) -> str | None:
    """The value after `name` in args, if it's there."""
    return args[args.index(name) + 1] if name in args[:-1] else None


async def main(action: str, *args: str) -> None:
    client = await connect()
    handle = client.get_workflow_handle(WORKFLOW_ID)
    if action == "start":
        await client.start_workflow(
            NetworkComplianceOrchestrator.run,
            # Day 17: --apply turns off dry run, and remediations really push config.
            # Day 24: --ticket CHG0042 goes with every remediation.
            OrchestratorInput(
                dry_run="--apply" not in args, change_ticket=option(args, "--ticket")
            ),
            id=WORKFLOW_ID,
            task_queue=ORCHESTRATION_TASK_QUEUE,
        )
        print(f"started {WORKFLOW_ID} ({'applying fixes' if '--apply' in args else 'dry run'})")
    elif action == "status":
        cycles = await handle.query(NetworkComplianceOrchestrator.cycles)
        state = await handle.query(NetworkComplianceOrchestrator.compliance)
        print(f"after {cycles} cycle(s):")
        for device, s in sorted(state.items()):
            problems = "; ".join(f"{d.kind}: {d.actual} (want {d.expected})" for d in s.drift)
            print(f"  {device:<11} {s.status:<9} {problems or s.error or ''}")
            if s.remediation:
                print(f"  {'':<11} {'':<9} -> {s.remediation}")
    elif action == "force-check":
        await handle.signal(NetworkComplianceOrchestrator.force_check)
        print("sent force_check")
    elif action == "interval":
        seconds = await handle.execute_update(
            NetworkComplianceOrchestrator.set_interval,
            SetIntervalRequest(interval_seconds=int(args[0])),
        )
        print(f"interval is now {seconds} s")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(main(*sys.argv[1:]))
