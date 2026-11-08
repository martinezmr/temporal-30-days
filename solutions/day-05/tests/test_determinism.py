"""Day 4: workflow time comes from history, and replay catches code that changed shape."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from temporalio import workflow
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

# This file defines a workflow, so the sandbox re-imports it: pass the app modules through,
# exactly as workflow files do.
with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.facts import get_device_facts
    from netops_temporal.models import FactsReport, FactsRequest
    from netops_temporal.workflows.facts import GetFactsWorkflow


@pytest.fixture(autouse=True)
def mock_lab(monkeypatch):
    monkeypatch.setenv("LAB_MODE", "mock")
    monkeypatch.delenv("MOCK_UNREACHABLE", raising=False)
    monkeypatch.delenv("MOCK_AUTH_FAIL", raising=False)


@workflow.defn(name="GetFactsWorkflow")
class ChangedGetFactsWorkflow:
    """GetFactsWorkflow after a careless edit: it now calls another activity first."""

    @workflow.run
    async def run(self, req: FactsRequest) -> FactsReport:
        await workflow.execute_activity(
            "say_hello", req.device, start_to_close_timeout=timedelta(seconds=10)
        )
        raise AssertionError("replay should have stopped before this line")


async def run_and_get_history(env: WorkflowEnvironment):
    with ThreadPoolExecutor(max_workers=4) as executor:
        async with Worker(
            env.client,
            task_queue="test",
            workflows=[GetFactsWorkflow],
            activities=[get_device_facts],
            activity_executor=executor,
        ):
            handle = await env.client.start_workflow(
                GetFactsWorkflow.run,
                FactsRequest(device="bos-rtr-01"),
                id=str(uuid.uuid4()),
                task_queue="test",
            )
            report = await handle.result()
            return report, await handle.fetch_history()


async def test_collected_at_uses_workflow_time():
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        before = await env.get_current_time()
        report, _ = await run_and_get_history(env)
    assert isinstance(report, FactsReport)
    assert report.facts.version == "4.32.0F"
    assert abs((report.collected_at - before).total_seconds()) < 1


async def test_replay_detects_nondeterminism():
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        _, history = await run_and_get_history(env)

    # The code that produced the history replays cleanly...
    await Replayer(
        workflows=[GetFactsWorkflow], data_converter=pydantic_data_converter
    ).replay_workflow(history)

    # ...but the edited code asks for a different activity than history recorded.
    with pytest.raises(workflow.NondeterminismError):
        await Replayer(
            workflows=[ChangedGetFactsWorkflow], data_converter=pydantic_data_converter
        ).replay_workflow(history)
