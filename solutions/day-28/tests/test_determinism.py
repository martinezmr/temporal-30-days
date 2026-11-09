"""Day 4: workflow time comes from history, and replay catches code that changed shape."""

import uuid
from datetime import timedelta

import pytest
from temporalio import workflow
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer

# This file defines a workflow, so the sandbox re-imports it: pass the app modules through,
# exactly as workflow files do.
with workflow.unsafe.imports_passed_through():
    from netops_temporal.models import FactsReport, FactsRequest
    from netops_temporal.workflows.facts import GetFactsWorkflow


@workflow.defn(name="GetFactsWorkflow")
class ChangedGetFactsWorkflow:
    """GetFactsWorkflow after a careless edit: it now calls another activity first."""

    @workflow.run
    async def run(self, req: FactsRequest) -> FactsReport:
        await workflow.execute_activity(
            "say_hello", req.device, start_to_close_timeout=timedelta(seconds=10)
        )
        raise AssertionError("replay should have stopped before this line")


async def run_and_get_history(env, worker):
    handle = await env.client.start_workflow(
        GetFactsWorkflow.run,
        FactsRequest(device="bos-rtr-01"),
        id=str(uuid.uuid4()),
        task_queue=worker.task_queue,
    )
    report = await handle.result()
    return report, await handle.fetch_history()


async def test_collected_at_uses_workflow_time(workflow_env, worker):
    before = await workflow_env.get_current_time()
    report, _ = await run_and_get_history(workflow_env, worker)
    assert isinstance(report, FactsReport)
    assert report.facts.version == "4.32.0F"
    assert abs((report.collected_at - before).total_seconds()) < 1


async def test_replay_detects_nondeterminism(workflow_env, worker):
    _, history = await run_and_get_history(workflow_env, worker)

    # The code that produced the history replays cleanly...
    await Replayer(
        workflows=[GetFactsWorkflow], data_converter=pydantic_data_converter
    ).replay_workflow(history)

    # ...but the edited code asks for a different activity than history recorded.
    with pytest.raises(workflow.NondeterminismError):
        await Replayer(
            workflows=[ChangedGetFactsWorkflow], data_converter=pydantic_data_converter
        ).replay_workflow(history)
