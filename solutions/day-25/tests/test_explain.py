"""Day 25: the LLM call is an activity: retried when that can help, and never paid for twice."""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import httpx2  # what openai builds its HTTP errors from
import openai
import pytest
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment
from temporalio.worker import Worker

from netops_temporal.activities import explain
from netops_temporal.activities.explain import explain_drift
from netops_temporal.llm import client as llm
from netops_temporal.llm.client import LLMMalformedOutput
from netops_temporal.models import DriftExplanation, DriftReport, ExplainRequest, OrchestratorInput
from netops_temporal.workflows.orchestrator import NetworkComplianceOrchestrator

CONFIG_DRIFT = DriftReport(
    device="bos-acc-01",
    kind="config",
    expected="1 policy line(s) present",
    actual="1 missing",
    missing_lines=["ntp server 192.0.2.10"],
)
VERSION_DRIFT = DriftReport(
    device="nyc-acc-01", kind="version", expected="4.33.1F", actual="4.32.0F"
)


def test_llm_mode_overrides_lab_mode(monkeypatch, fake_llm):
    # Mock devices (LAB_MODE=mock) with a real model: LLM_MODE=live wins for the model.
    monkeypatch.setenv("LAB_MODE", "mock")
    monkeypatch.setenv("LLM_MODE", "live")
    fake_llm(FakeOpenAI(content='{"summary": "real", "risk": "low", "likely_cause": "x"}'))
    result = ActivityEnvironment().run(
        explain_drift, ExplainRequest(device="bos-acc-01", drift=[CONFIG_DRIFT])
    )
    assert result.summary == "real"


def test_explain_drift_mock():
    result = ActivityEnvironment().run(
        explain_drift, ExplainRequest(device="bos-acc-01", drift=[CONFIG_DRIFT])
    )
    assert isinstance(result, DriftExplanation)
    assert result.risk == "medium"
    assert "bos-acc-01" in result.summary
    # A version drift is the riskier kind: the canned answer depends on what drifted.
    upgrade = ActivityEnvironment().run(
        explain_drift, ExplainRequest(device="nyc-acc-01", drift=[VERSION_DRIFT])
    )
    assert upgrade.risk == "high"


class FakeOpenAI:
    """Stands in for openai.OpenAI: create() raises `error`, or returns `content`."""

    def __init__(self, content: str = "", error: Exception | None = None):
        self.content, self.error = content, error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def status_error(cls, status: int) -> openai.APIStatusError:
    request = httpx2.Request("POST", "http://localhost:11434/v1/chat/completions")
    return cls("nope", response=httpx2.Response(status, request=request), body=None)


@pytest.fixture
def fake_llm(monkeypatch):
    """A live model, with the OpenAI client replaced by whatever the test sets."""
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    def use(fake: FakeOpenAI):
        monkeypatch.setattr(llm, "openai_client", lambda: fake)

    return use


def test_auth_error_non_retryable(fake_llm):
    fake_llm(FakeOpenAI(error=status_error(openai.AuthenticationError, 401)))
    with pytest.raises(ApplicationError) as err:
        ActivityEnvironment().run(
            explain_drift, ExplainRequest(device="bos-acc-01", drift=[CONFIG_DRIFT])
        )
    # A bad token won't get better on the next attempt: fail now, don't burn four tries.
    assert err.value.type == "LLMAuth"
    assert err.value.non_retryable


def test_rate_limit_is_retryable(fake_llm):
    fake_llm(FakeOpenAI(error=status_error(openai.RateLimitError, 429)))
    with pytest.raises(llm.LLMUnavailable) as err:  # a plain exception: Temporal retries it
        ActivityEnvironment().run(
            explain_drift, ExplainRequest(device="bos-acc-01", drift=[CONFIG_DRIFT])
        )
    # Without the HTTP library's exception chain, so the UI can show it as the last failure.
    assert err.value.__cause__ is None


@pytest.mark.parametrize(
    "content",
    [
        "Sure! Here's the explanation: the device is missing NTP.",  # not JSON at all
        '{"summary": "missing ntp", "risk": "extreme", "likely_cause": "?"}',  # off-schema
        '{"summary": "missing ntp"}',  # fields missing
    ],
)
def test_malformed_llm_json_is_retryable(fake_llm, content):
    fake_llm(FakeOpenAI(content=content))
    # Never a half-parsed explanation: the attempt fails, with an error Temporal retries.
    with pytest.raises(LLMMalformedOutput):
        ActivityEnvironment().run(
            explain_drift, ExplainRequest(device="bos-acc-01", drift=[CONFIG_DRIFT])
        )


@workflow.defn(sandboxed=False)
class ExplainOnce:
    @workflow.run
    async def run(self, req: ExplainRequest) -> DriftExplanation:
        return await workflow.execute_activity(
            explain_drift,
            req,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=4),
        )


async def test_malformed_mock_output_succeeds_on_retry(workflow_env, monkeypatch):
    monkeypatch.setenv("MOCK_LLM_MALFORMED", "1")  # the first attempt gets garbage
    with ThreadPoolExecutor(max_workers=2) as executor:
        async with Worker(
            workflow_env.client,
            task_queue="explain",
            workflows=[ExplainOnce],
            activities=[explain_drift],
            activity_executor=executor,
        ):
            handle = await workflow_env.client.start_workflow(
                ExplainOnce.run,
                ExplainRequest(device="bos-acc-01", drift=[CONFIG_DRIFT]),
                id=f"explain-{uuid.uuid4()}",
                task_queue="explain",
            )
            result = await handle.result()
    assert result.risk == "medium"
    attempts = [
        e.activity_task_started_event_attributes.attempt
        for e in (await handle.fetch_history()).events
        if e.HasField("activity_task_started_event_attributes")
    ]
    assert attempts == [2]  # the history records the attempt that succeeded


async def wait_for_cycles(handle, n):
    for _ in range(200):
        if await handle.query(NetworkComplianceOrchestrator.cycles) >= n:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"cycle {n} never finished")


async def test_explanation_reused_after_worker_restart(dev_env, start_workers, monkeypatch):
    calls = []
    real = explain.complete_structured

    def counting(*args):
        calls.append(args)
        return real(*args)

    monkeypatch.setattr(explain, "complete_structured", counting)
    async with start_workers(dev_env.client) as worker:
        handle = await dev_env.client.start_workflow(
            NetworkComplianceOrchestrator.run,
            OrchestratorInput(devices=["bos-acc-01"], interval_seconds=3600),
            id=f"orchestrator-{uuid.uuid4()}",
            task_queue=worker.task_queue,
        )
        await wait_for_cycles(handle, 1)
        before = (await handle.query(NetworkComplianceOrchestrator.compliance))["bos-acc-01"]
    # That worker is gone. The new one has nothing cached, so to answer the query it rebuilds
    # the orchestrator from history, using the recorded explanation.
    async with start_workers(dev_env.client):
        after = (await handle.query(NetworkComplianceOrchestrator.compliance))["bos-acc-01"]
        # And a new cycle that finds the same drift keeps the explanation it already has.
        await handle.signal(NetworkComplianceOrchestrator.force_check)
        await wait_for_cycles(handle, 2)
        cycle2 = (await handle.query(NetworkComplianceOrchestrator.compliance))["bos-acc-01"]
    await handle.terminate()
    assert before.explanation is not None
    assert before.explanation.risk == "medium"
    assert after.explanation == before.explanation == cycle2.explanation
    assert len(calls) == 1  # one LLM call, paid for once
