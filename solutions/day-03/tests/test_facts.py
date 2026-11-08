"""Day 3: typed facts, and errors that are retried only when retrying can help."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pyeapi.eapilib
import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Worker

from netops_temporal.activities.facts import get_device_facts
from netops_temporal.devices import eapi
from netops_temporal.devices.errors import DeviceAuthError, DeviceUnreachableError
from netops_temporal.models import DeviceFacts, FactsRequest
from netops_temporal.workflows.facts import GetFactsWorkflow


@pytest.fixture(autouse=True)
def mock_lab(monkeypatch):
    monkeypatch.setenv("LAB_MODE", "mock")
    monkeypatch.delenv("MOCK_UNREACHABLE", raising=False)
    monkeypatch.delenv("MOCK_AUTH_FAIL", raising=False)


async def run_facts_workflow(device: str):
    """Run GetFactsWorkflow in a time-skipping test server; return (result or error, history)."""
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
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
                    FactsRequest(device=device),
                    id=str(uuid.uuid4()),
                    task_queue="test",
                )
                try:
                    result = await handle.result()
                except WorkflowFailureError as err:
                    result = err
                history = await handle.fetch_history()
    return result, history


def attempts(history) -> int:
    [started] = [
        e for e in history.events if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED
    ]
    return started.activity_task_started_event_attributes.attempt


def root_cause(err: WorkflowFailureError) -> ApplicationError:
    assert isinstance(err.cause, ActivityError)
    assert isinstance(err.cause.cause, ApplicationError)
    return err.cause.cause


def test_get_device_facts_mock():
    facts = ActivityEnvironment().run(get_device_facts, FactsRequest(device="bos-rtr-01"))
    assert facts == DeviceFacts(device="bos-rtr-01", model="cEOSLab", version="4.32.0F")


async def test_facts_roundtrip_typed():
    result, _ = await run_facts_workflow("nyc-acc-01")
    assert isinstance(result, DeviceFacts)
    assert result.version == "4.32.0F"


async def test_auth_failure_is_not_retried(monkeypatch):
    monkeypatch.setenv("MOCK_AUTH_FAIL", "1")
    result, history = await run_facts_workflow("bos-rtr-01")
    assert root_cause(result).type == "AuthError"
    assert root_cause(result).non_retryable
    assert attempts(history) == 1


async def test_unknown_device_is_not_retried():
    result, history = await run_facts_workflow("nope")
    assert root_cause(result).type == "UnknownDevice"
    assert attempts(history) == 1


async def test_unreachable_still_retries(monkeypatch):
    monkeypatch.setenv("MOCK_UNREACHABLE", "bos-rtr-01")
    result, history = await run_facts_workflow("bos-rtr-01")
    assert isinstance(result, WorkflowFailureError)
    assert attempts(history) == 5


class FailingNode:
    def __init__(self, message: str):
        self.message = message

    def run_commands(self, commands):
        raise pyeapi.eapilib.ConnectionError("https://127.0.0.1:8441", self.message)


def test_eapi_maps_unauthorized(monkeypatch):
    monkeypatch.setenv("LAB_MODE", "live")
    message = "Unauthorized. Unable to authenticate user: Bad username/password combination"
    monkeypatch.setattr(eapi.pyeapi, "connect", lambda **_: FailingNode(message))
    with pytest.raises(DeviceAuthError):
        eapi.run_show("bos-rtr-01", ["show version"])


def test_eapi_maps_connection_refused(monkeypatch):
    monkeypatch.setenv("LAB_MODE", "live")
    message = "Socket error during eAPI connection: [Errno 61] Connection refused"
    monkeypatch.setattr(eapi.pyeapi, "connect", lambda **_: FailingNode(message))
    with pytest.raises(DeviceUnreachableError):
        eapi.run_show("bos-rtr-01", ["show version"])
