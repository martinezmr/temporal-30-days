"""Day 26: the troubleshooting agent. It looks before it answers, and it can only look.

Its tools are activities (activity_as_tool), so every command it runs is an activity in the
workflow's history, with a timeout and retries, like the rest of the course's device I/O.
"""

import asyncio
import dataclasses
from dataclasses import dataclass
from datetime import timedelta

from agents import Agent, FunctionTool, RunContextWrapper, function_tool
from temporalio.common import RetryPolicy
from temporalio.contrib.openai_agents.workflow import activity_as_tool

from netops_temporal.activities.show import show_command
from netops_temporal.constants import DEVICE_IO_TASK_QUEUE
from netops_temporal.models import ChangeProposal

INSTRUCTIONS = """You troubleshoot Arista EOS devices for a network operations team.
Use your tools to look at the device before you conclude anything; never guess its state.
You can only run read-only `show` commands. Start broad (show interfaces status, show lldp
neighbors, show logging 50), then narrow down. When you know the cause, say what you found,
citing the command output. If a config change would fix it, call propose_change with the
exact EOS config lines; a human reviews it. You never change anything yourself."""


def safe_tool(tool: FunctionTool) -> FunctionTool:
    """Hand a tool's failure back to the model as its answer, instead of failing the workflow.

    A refused command (CommandNotAllowed), arguments the model got wrong, a device that stays
    unreachable after the retries: the model reads what went wrong and decides what to do next.
    Without this, the error ends the agent's run, or (for bad arguments) fails the workflow
    task over and over.
    """
    invoke = tool.on_invoke_tool

    async def on_invoke_tool(ctx, arguments: str):
        try:
            return await invoke(ctx, arguments)
        except asyncio.CancelledError:
            raise  # a cancelled workflow stops; that's not the model's problem to solve
        except Exception as err:
            reason = err.cause if getattr(err, "cause", None) else err  # ActivityError -> why
            return f"Tool error: {reason}"

    return dataclasses.replace(tool, on_invoke_tool=on_invoke_tool)


SHOW = safe_tool(
    activity_as_tool(
        show_command,
        task_queue=DEVICE_IO_TASK_QUEUE,
        start_to_close_timeout=timedelta(seconds=60),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )
)


@dataclass
class Investigation:
    """The run's context: shared by the agent's in-workflow tools, kept by the workflow."""

    device: str
    proposal: ChangeProposal | None = None


# Not an activity: it does no I/O, it only writes the proposal down. A function tool runs in
# the workflow, so it must be deterministic, and it's the only kind that can change the context.
# `async def`: the Agents SDK runs a plain `def` tool on a thread, and workflows can't.
@function_tool
async def propose_change(
    ctx: RunContextWrapper[Investigation], lines: list[str], rationale: str
) -> str:
    """Record EOS config lines that would fix the problem, for a human to review. Nothing is
    applied to the device."""
    ctx.context.proposal = ChangeProposal(
        device=ctx.context.device, lines=lines, rationale=rationale
    )
    return "Recorded for review. Nothing has been changed on the device."


def troubleshooter() -> Agent[Investigation]:
    # No output_type: a structured final answer stops some models (Ollama's among them) from
    # calling tools at all. The answer is plain text; a proposal comes through propose_change.
    return Agent(
        name="EOS troubleshooter",
        instructions=INSTRUCTIONS,
        tools=[SHOW, propose_change],
    )
