"""Day 26: a troubleshooting agent whose model calls and tool calls are activities."""

import json
import uuid

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client
from temporalio.contrib.openai_agents.testing import AgentEnvironment, ResponseBuilders, TestModel
from temporalio.converter import DataConverter
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from netops_temporal.activities.show import show_command
from netops_temporal.llm.agent_models import ScriptedTroubleshooter
from netops_temporal.models import TroubleshootReport, TroubleshootRequest
from netops_temporal.workflows.troubleshoot import TroubleshootWorkflow


@pytest.mark.parametrize(
    "command",
    [
        "configure",
        "reload",
        "show run | bash ls",
        "show interfaces status | include Et1 | redirect flash:x",
        "  write memory",
    ],
)
def test_show_tool_rejects_non_show_commands(command):
    with pytest.raises(ApplicationError) as err:
        ActivityEnvironment().run(show_command, "bos-acc-01", command)
    # Non-retryable: the same command is just as forbidden on the next attempt.
    assert err.value.type == "CommandNotAllowed"
    assert err.value.non_retryable


def test_show_tool_runs_show_commands_with_filters():
    output = ActivityEnvironment().run(
        show_command, "bos-acc-01", "show interfaces status | include Et1"
    )
    lines = output.splitlines()
    assert lines and all("Et1" in line for line in lines)


def test_mock_lab_answers_unknown_show_commands_like_eos():
    # Not an exception (which Temporal would retry): an error message the agent can read.
    output = ActivityEnvironment().run(show_command, "bos-acc-01", "show bgp summary")
    assert output.startswith("% Invalid input")


def activity_types(events) -> list[str]:
    return [
        e.activity_task_scheduled_event_attributes.activity_type.name
        for e in events
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
    ]


async def troubleshoot(env, start_workers, model, symptom="users on Et1 can't connect"):
    """Run TroubleshootWorkflow with `model` playing the LLM. Returns (report, history)."""
    async with AgentEnvironment(model=model) as agents:
        # The plugin brings its own payload converter: start from the default one (Day 26 in
        # client.py), not the Pydantic one the other tests use.
        client = agents.applied_on_client(
            Client(**{**env.client.config(), "data_converter": DataConverter.default})
        )
        async with start_workers(client) as worker:
            handle = await client.start_workflow(
                TroubleshootWorkflow.run,
                TroubleshootRequest(device="bos-acc-01", symptom=symptom),
                id=f"troubleshoot-{uuid.uuid4()}",
                task_queue=worker.task_queue,
            )
            return await handle.result(), await handle.fetch_history()


async def test_agent_calls_tool_then_answers(workflow_env, start_workers):
    report, history = await troubleshoot(workflow_env, start_workers, ScriptedTroubleshooter())
    assert isinstance(report, TroubleshootReport)
    assert report.device == "bos-acc-01"
    assert "Et1" in report.findings
    assert report.proposed_change is None  # read-only today: nothing to propose
    # The whole agent loop, in the history: the model asks for a tool, the tool runs, and the
    # model reads its output and answers. Each step is an activity.
    assert activity_types(history.events) == [
        "invoke_model_activity",
        "show_command",
        "invoke_model_activity",
    ]


def show(command: str, **extra) -> object:
    """A model response that calls show_command."""
    args = {"device": "bos-acc-01", "command": command, **extra}
    return ResponseBuilders.tool_call(json.dumps(args), "show_command")


async def test_refused_command_goes_back_to_the_model(workflow_env, start_workers):
    model = TestModel.returning_responses(
        [show("configure terminal"), ResponseBuilders.output_message("I can only look.")]
    )
    report, history = await troubleshoot(workflow_env, start_workers, model, "fix it")
    # The refusal didn't crash the workflow: the model got it as the tool's answer, and
    # answered. The device was never touched.
    assert report.findings == "I can only look."
    failures = [
        e.activity_task_failed_event_attributes.failure.message
        for e in history.events
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_FAILED
    ]
    assert len(failures) == 1 and "only show commands" in failures[0]


async def test_bad_tool_arguments_go_back_to_the_model(workflow_env, start_workers):
    model = TestModel.returning_responses(
        [
            ResponseBuilders.tool_call(json.dumps({"device": "bos-acc-01"}), "show_command"),
            ResponseBuilders.output_message("Sorry, I forgot the command."),
        ]
    )
    report, history = await troubleshoot(workflow_env, start_workers, model)
    # A model that gets the arguments wrong is told so, instead of failing the workflow task
    # over and over.
    assert report.findings == "Sorry, I forgot the command."
    assert activity_types(history.events) == ["invoke_model_activity", "invoke_model_activity"]


async def test_proposed_change_is_reported_not_applied(workflow_env, start_workers):
    lines = ["interface Ethernet1", "no shutdown"]
    model = TestModel.returning_responses(
        [
            ResponseBuilders.tool_call(
                json.dumps({"lines": lines, "rationale": "Et1 is admin down"}), "propose_change"
            ),
            ResponseBuilders.output_message("Et1 is shut down; I proposed a fix."),
        ]
    )
    report, history = await troubleshoot(workflow_env, start_workers, model)
    assert report.proposed_change.lines == lines
    assert report.proposed_change.rationale == "Et1 is admin down"
    # propose_change runs in the workflow: no activity, nothing sent to the device.
    assert activity_types(history.events) == ["invoke_model_activity", "invoke_model_activity"]
