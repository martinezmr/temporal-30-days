"""Day 6: the three layers of Temporal tests, side by side."""

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError, WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer, Worker

from netops_temporal.models import DeviceFacts, FactsReport, FactsRequest
from netops_temporal.tools.export_history import export_history
from netops_temporal.workers.main import WORKFLOWS
from netops_temporal.workflows.facts import GetFactsWorkflow

HISTORIES = Path(__file__).parent / "histories"


# Layer 2: a workflow test with a stubbed activity. Same name as the real activity, so the
# workflow can't tell the difference, and no device or mock lab is involved at all.
@activity.defn(name="get_device_facts")
def stub_get_device_facts(req: FactsRequest) -> DeviceFacts:
    return DeviceFacts(device=req.device, model="stub", version="9.99.9F")


async def test_facts_workflow_with_stubbed_activity(workflow_env):
    with ThreadPoolExecutor(max_workers=1) as executor:
        async with Worker(
            workflow_env.client,
            task_queue="stubbed",
            workflows=[GetFactsWorkflow],
            activities=[stub_get_device_facts],
            activity_executor=executor,
        ):
            report = await workflow_env.client.execute_workflow(
                GetFactsWorkflow.run,
                FactsRequest(device="bos-rtr-01"),
                id=str(uuid.uuid4()),
                task_queue="stubbed",
            )
    assert report.facts == DeviceFacts(device="bos-rtr-01", model="stub", version="9.99.9F")


async def test_retry_backoff_uses_time_skipping(workflow_env, worker, monkeypatch):
    """Five attempts with 2+4+8+16 s of backoff, finished in well under 30 s of real time."""
    monkeypatch.setenv("MOCK_UNREACHABLE", "bos-rtr-01")
    started = time.monotonic()
    with pytest.raises(WorkflowFailureError):
        await workflow_env.client.execute_workflow(
            GetFactsWorkflow.run,
            FactsRequest(device="bos-rtr-01"),
            id=str(uuid.uuid4()),
            task_queue=worker.task_queue,
        )
    assert time.monotonic() - started < 5


# Layer 3: replay tests. Every history in tests/histories/ must still replay against
# today's workflow code. This is the test that catches non-deterministic changes.
def history_files() -> list[Path]:
    return sorted(HISTORIES.glob("*.json"))


@pytest.mark.parametrize("path", history_files(), ids=lambda p: p.stem)
async def test_replay_committed_histories(path):
    history = WorkflowHistory.from_json(path.stem, path.read_text())
    await Replayer(workflows=WORKFLOWS, data_converter=pydantic_data_converter).replay_workflow(
        history
    )


def test_committed_histories_exist():
    assert {p.stem for p in history_files()} >= {"get_facts", "show_tech", "config_backup"}


async def test_export_history_writes_replayable_json(workflow_env, worker, tmp_path):
    workflow_id = f"facts-{uuid.uuid4()}"
    report = await workflow_env.client.execute_workflow(
        GetFactsWorkflow.run,
        FactsRequest(device="nyc-rtr-01"),
        id=workflow_id,
        task_queue=worker.task_queue,
    )
    assert isinstance(report, FactsReport)

    out = tmp_path / "facts.json"
    await export_history(workflow_env.client, workflow_id, out)

    assert json.loads(out.read_text())["events"]
    history = WorkflowHistory.from_json(workflow_id, out.read_text())
    await Replayer(workflows=WORKFLOWS, data_converter=pydantic_data_converter).replay_workflow(
        history
    )
