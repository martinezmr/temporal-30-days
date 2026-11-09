"""Days 26-27: a troubleshooting agent whose model calls and tool calls are activities, and
(Day 27) whose proposals need a human's approval."""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager

import pytest
from agents.tracing import get_trace_provider
from agents.tracing.processors import BackendSpanExporter
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowUpdateFailedError
from temporalio.contrib.openai_agents.testing import AgentEnvironment, ResponseBuilders, TestModel
from temporalio.converter import DataConverter
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from netops_temporal.activities.show import show_command
from netops_temporal.llm.agent_models import ScriptedTroubleshooter
from netops_temporal.mock import state as mock_state
from netops_temporal.models import Decision, TroubleshootReport, TroubleshootRequest
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


async def test_agent_traces_are_not_exported(workflow_env, start_workers, monkeypatch):
    # Traces include device output. The Agents SDK would upload them to OpenAI for anyone with
    # OPENAI_API_KEY set, and the plugin's spans ignore set_tracing_disabled.
    exported = []
    monkeypatch.setattr(BackendSpanExporter, "export", lambda _, items: exported.extend(items))
    await troubleshoot(workflow_env, start_workers, ScriptedTroubleshooter())
    get_trace_provider().force_flush()
    assert exported == []


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


# Day 27: the agent proposes, a human decides, and Day 17's saga applies it.

NTP = "ntp server 192.0.2.10"  # the line bos-acc-01's policy says is missing


def proposing(lines: list[str]) -> TestModel:
    """A model that proposes `lines` and then answers."""
    return TestModel.returning_responses(
        [
            ResponseBuilders.tool_call(
                json.dumps({"lines": lines, "rationale": "the policy requires it"}),
                "propose_change",
            ),
            ResponseBuilders.output_message("NTP is missing; I proposed adding it."),
        ]
    )


@asynccontextmanager
async def awaiting_approval(env, start_workers, model, **request):
    """Start an investigation by alice and yield its handle once it waits for a decision."""
    async with AgentEnvironment(model=model) as agents:
        client = agents.applied_on_client(
            Client(**{**env.client.config(), "data_converter": DataConverter.default})
        )
        async with start_workers(client) as worker:
            handle = await client.start_workflow(
                TroubleshootWorkflow.run,
                TroubleshootRequest(
                    device="bos-acc-01", symptom="NTP is wrong", requested_by="alice", **request
                ),
                id=f"troubleshoot-{uuid.uuid4()}",
                task_queue=worker.task_queue,
            )
            for _ in range(100):
                if await handle.query(TroubleshootWorkflow.stage) == "awaiting_approval":
                    break
                await asyncio.sleep(0.1)
            yield handle


async def test_approved_proposal_runs_remediation(workflow_env, start_workers):
    async with awaiting_approval(workflow_env, start_workers, proposing([NTP])) as handle:
        assert (await handle.query(TroubleshootWorkflow.proposal)).lines == [NTP]
        await handle.execute_update(
            TroubleshootWorkflow.decide, Decision(approve=True, approver="bob")
        )
        report = await handle.result()
    assert report.outcome == "approved by bob: pushed 1 line(s)"
    assert mock_state.applied_lines("bos-acc-01") == [NTP]
    # The push went through the compliance team's remediate operation (Day 23), never through
    # the agent: its tools can't change anything.
    operations = [
        e.nexus_operation_scheduled_event_attributes.operation
        for e in (await handle.fetch_history()).events
        if e.event_type == EventType.EVENT_TYPE_NEXUS_OPERATION_SCHEDULED
    ]
    assert operations == ["remediate"]


async def test_self_approval_rejected_by_validator(workflow_env, start_workers):
    async with awaiting_approval(workflow_env, start_workers, proposing([NTP])) as handle:
        with pytest.raises(WorkflowUpdateFailedError) as err:
            await handle.execute_update(
                TroubleshootWorkflow.decide, Decision(approve=True, approver="alice")
            )
        assert "can't approve your own" in str(err.value.cause)
        # Still waiting: the rejected update left no trace in the workflow's state.
        assert await handle.query(TroubleshootWorkflow.stage) == "awaiting_approval"
        await handle.terminate()
    assert mock_state.applied_lines("bos-acc-01") == []


async def test_second_decision_rejected(workflow_env, start_workers, monkeypatch):
    monkeypatch.setenv("MOCK_CLI_DELAY", "1")  # keeps the remediation busy for a few seconds
    async with awaiting_approval(workflow_env, start_workers, proposing([NTP])) as handle:
        await handle.execute_update(
            TroubleshootWorkflow.decide, Decision(approve=True, approver="bob")
        )
        # While bob's approval is being applied, carol tries to decide too.
        with pytest.raises(WorkflowUpdateFailedError) as err:
            await handle.execute_update(
                TroubleshootWorkflow.decide, Decision(approve=False, approver="carol")
            )
        assert "not awaiting approval" in str(err.value.cause)
        report = await handle.result()
    assert report.outcome == "approved by bob: pushed 1 line(s)"


async def test_rejected_proposal_changes_nothing(workflow_env, start_workers):
    async with awaiting_approval(workflow_env, start_workers, proposing([NTP])) as handle:
        await handle.execute_update(
            TroubleshootWorkflow.decide, Decision(approve=False, approver="bob")
        )
        report = await handle.result()
    assert report.outcome == "rejected by bob: nothing changed"
    assert mock_state.applied_lines("bos-acc-01") == []


async def test_no_decision_times_out_without_change(workflow_env, start_workers):
    async with awaiting_approval(workflow_env, start_workers, proposing([NTP])) as handle:
        report = await handle.result()  # the test server skips the 30 minutes
    assert report.outcome == "approval timed out: nothing changed"
    assert mock_state.applied_lines("bos-acc-01") == []


async def test_mode_commands_stripped_from_proposal(workflow_env, start_workers):
    model = proposing(["configure terminal", NTP, "end", "write memory"])
    async with awaiting_approval(workflow_env, start_workers, model) as handle:
        # Models like to write a whole CLI session. The saga pushes config lines only.
        assert (await handle.query(TroubleshootWorkflow.proposal)).lines == [NTP]
        await handle.terminate()
