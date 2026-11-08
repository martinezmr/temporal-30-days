"""Day 2: get_device_facts and GetFactsWorkflow, against the mock lab."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ActivityError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Worker

from netops_temporal.activities.facts import get_device_facts
from netops_temporal.workflows.facts import GetFactsWorkflow


@pytest.fixture(autouse=True)
def mock_lab(monkeypatch):
    monkeypatch.setenv("LAB_MODE", "mock")
    monkeypatch.delenv("MOCK_UNREACHABLE", raising=False)
    monkeypatch.delenv("MOCK_AUTH_FAIL", raising=False)


async def run_facts_workflow(device: str):
    """Start GetFactsWorkflow in a time-skipping test server; return (result or error, handle)."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        with ThreadPoolExecutor(max_workers=4) as executor:
            async with Worker(
                env.client,
                task_queue="test",
                workflows=[GetFactsWorkflow],
                activities=[get_device_facts],
                activity_executor=executor,
            ):
                handle = await env.client.start_workflow(
                    GetFactsWorkflow.run, device, id=str(uuid.uuid4()), task_queue="test"
                )
                try:
                    result = await handle.result()
                except WorkflowFailureError as err:
                    result = err
                history = await handle.fetch_history()
    return result, history


def test_get_device_facts_mock():
    facts = ActivityEnvironment().run(get_device_facts, "bos-rtr-01")
    assert facts == {"device": "bos-rtr-01", "model": "cEOSLab", "version": "4.32.0F"}


async def test_facts_workflow_end_to_end():
    result, _ = await run_facts_workflow("nyc-acc-01")
    assert result == {"device": "nyc-acc-01", "model": "cEOSLab", "version": "4.32.0F"}


async def test_facts_workflow_fails_after_five_attempts(monkeypatch):
    monkeypatch.setenv("MOCK_UNREACHABLE", "bos-rtr-01")
    result, history = await run_facts_workflow("bos-rtr-01")

    assert isinstance(result, WorkflowFailureError)
    assert isinstance(result.cause, ActivityError)
    [started] = [
        e for e in history.events if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED
    ]
    assert started.activity_task_started_event_attributes.attempt == 5
