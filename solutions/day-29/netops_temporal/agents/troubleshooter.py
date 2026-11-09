"""Day 26: the troubleshooting agent. It looks before it answers, and it can only look.

Its tools are activities, so every command it runs is an activity in the workflow's history,
with a timeout and retries, like the rest of the course's device I/O.

Day 28: the device tools come from the netops MCP server (mcp_server/netops_tools.py), and an
output guardrail stops proposals that aren't compliance policy lines.
"""

from dataclasses import dataclass
from datetime import timedelta

from agents import (
    Agent,
    GuardrailFunctionOutput,
    RunContextWrapper,
    function_tool,
    output_guardrail,
)
from temporalio.common import RetryPolicy
from temporalio.contrib.openai_agents.workflow import temporal_mcp_server
from temporalio.workflow import ActivityConfig

from netops_temporal.constants import DEVICE_IO_TASK_QUEUE
from netops_temporal.guardrails import non_policy_lines
from netops_temporal.models import ChangeProposal

INSTRUCTIONS = """You troubleshoot Arista EOS devices for a network operations team.
Use your tools to look at the device before you conclude anything; never guess its state.
You can only run read-only `show` commands. Start broad (show interfaces status, show lldp
neighbors, show logging 50), then narrow down. When you know the cause, say what you found,
citing the command output. If a config change would fix it, call propose_change with the
exact EOS config lines; a human reviews it. You never change anything yourself. You may only
propose lines from the compliance policy, such as `ntp server 192.0.2.10`."""


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


# Runs in the workflow after the agent's final answer, before Runner.run returns. A tripwire
# raises OutputGuardrailTripwireTriggered: the proposal never reaches a human.
@output_guardrail
async def policy_lines_only(
    ctx: RunContextWrapper[Investigation], agent: Agent, output: object
) -> GuardrailFunctionOutput:
    proposal = ctx.context.proposal
    rejected = non_policy_lines(proposal.lines) if proposal else []
    return GuardrailFunctionOutput(output_info=rejected, tripwire_triggered=bool(rejected))


def netops_mcp():
    """The netops MCP server, through the plugin: listing its tools and calling one are
    activities on the device-io workers, which start the server (llm/agent_models.py)."""
    return temporal_mcp_server(
        "netops",
        activity_config=ActivityConfig(
            task_queue=DEVICE_IO_TASK_QUEUE,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=3),
        ),
    )


def troubleshooter() -> Agent[Investigation]:
    # No output_type: a structured final answer stops some models (Ollama's among them) from
    # calling tools at all. The answer is plain text; a proposal comes through propose_change.
    return Agent(
        name="EOS troubleshooter",
        instructions=INSTRUCTIONS,
        tools=[propose_change],
        mcp_servers=[netops_mcp()],  # Day 28: show and facts
        output_guardrails=[policy_lines_only],
    )
