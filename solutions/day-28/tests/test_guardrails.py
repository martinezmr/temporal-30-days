"""Day 28: guardrails are code you can test, not sentences in a prompt."""

import json
import uuid

import pytest
from temporalio.client import Client
from temporalio.contrib.openai_agents.testing import AgentEnvironment, ResponseBuilders, TestModel
from temporalio.converter import DataConverter

from netops_temporal.guardrails import CommandNotAllowed, check_command
from netops_temporal.llm.agent_models import netops_server
from netops_temporal.mock import state as mock_state
from netops_temporal.models import TroubleshootRequest
from netops_temporal.workflows.troubleshoot import TroubleshootWorkflow

# The netops MCP server the real plugin starts (Day 28), for the test plugin too.
MCP = {"netops": netops_server}


@pytest.mark.parametrize(
    "command",
    ["show version", "show ip bgp summary | include Estab", "show run | section ntp"],
)
def test_check_command_allows_show_commands(command):
    check_command(command)  # no exception


@pytest.mark.parametrize(
    "command",
    ["configure", "write", "reload", "show run | bash", "bash", "show version | redirect x"],
)
def test_check_command_allowlist(command):
    with pytest.raises(CommandNotAllowed):
        check_command(command)


async def run_agent(env, start_workers, model) -> object:
    async with AgentEnvironment(model=model, mcp_servers=MCP) as agents:
        client = agents.applied_on_client(
            Client(**{**env.client.config(), "data_converter": DataConverter.default})
        )
        async with start_workers(client) as worker:
            return await client.execute_workflow(
                TroubleshootWorkflow.run,
                TroubleshootRequest(device="bos-acc-01", symptom="?", requested_by="alice"),
                id=f"troubleshoot-{uuid.uuid4()}",
                task_queue=worker.task_queue,
            )


def proposing(lines):
    return TestModel.returning_responses(
        [
            ResponseBuilders.tool_call(
                json.dumps({"lines": lines, "rationale": "trust me"}), "propose_change"
            ),
            ResponseBuilders.output_message("I proposed a fix."),
        ]
    )


async def test_output_guardrail_rejects_non_policy_lines(workflow_env, start_workers):
    report = await run_agent(
        workflow_env, start_workers, proposing(["interface Ethernet1", "shutdown"])
    )
    # The proposal never reaches a human, let alone a device: only policy lines may be proposed.
    assert report.outcome.startswith("proposal blocked by guardrail")
    assert "shutdown" in report.outcome
    assert mock_state.applied_lines("bos-acc-01") == []


async def test_output_guardrail_allows_policy_lines(workflow_env, start_workers):
    model = proposing(["ntp server 192.0.2.10"])
    async with AgentEnvironment(model=model, mcp_servers=MCP) as agents:
        client = agents.applied_on_client(
            Client(**{**workflow_env.client.config(), "data_converter": DataConverter.default})
        )
        async with start_workers(client) as worker:
            handle = await client.start_workflow(
                TroubleshootWorkflow.run,
                TroubleshootRequest(device="bos-acc-01", symptom="?", requested_by="alice"),
                id=f"troubleshoot-{uuid.uuid4()}",
                task_queue=worker.task_queue,
            )
            report = await handle.result()  # nobody approves: times out (time skipping)
    assert report.outcome == "approval timed out: nothing changed"
