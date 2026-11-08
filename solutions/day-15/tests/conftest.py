"""Shared test setup: mock lab on, a time-skipping Temporal server, and a worker for it."""

import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from netops_temporal.activities import backup, show_tech
from netops_temporal.workers.main import ACTIVITIES, WORKFLOWS

TASK_QUEUE = "test"


@pytest.fixture(autouse=True)
def mock_lab(monkeypatch, tmp_path):
    """Every test runs against the mock lab, with outputs in a throwaway directory."""
    monkeypatch.setenv("LAB_MODE", "mock")
    # Day 14: the mock lab keeps pushed config in OUTPUT_DIR/mock-state.json.
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    for name in ("MOCK_UNREACHABLE", "MOCK_AUTH_FAIL", "MOCK_CLI_DELAY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(show_tech, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(backup, "OUTPUT_DIR", tmp_path)
    return tmp_path


@pytest.fixture
async def workflow_env():
    """A local Temporal test server that skips ahead whenever workflows are only waiting."""
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        yield env


@pytest.fixture
async def worker(workflow_env):
    """A worker on TASK_QUEUE with the same workflows and activities as the real one."""
    with ThreadPoolExecutor(max_workers=10) as executor:
        async with Worker(
            workflow_env.client,
            task_queue=TASK_QUEUE,
            workflows=WORKFLOWS,
            activities=ACTIVITIES,
            activity_executor=executor,
            max_concurrent_activities=10,
        ) as running:
            yield running


@pytest.fixture
async def dev_env():
    """A real Temporal dev server, for the few features the time-skipping server doesn't
    implement faithfully (Day 15: parent close policies). Uses the `temporal` CLI if it's
    installed, otherwise downloads the dev server once."""
    async with await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter,
        dev_server_existing_path=shutil.which("temporal"),
    ) as env:
        yield env


@pytest.fixture
async def dev_worker(dev_env):
    with ThreadPoolExecutor(max_workers=10) as executor:
        async with Worker(
            dev_env.client,
            task_queue=TASK_QUEUE,
            workflows=WORKFLOWS,
            activities=ACTIVITIES,
            activity_executor=executor,
            max_concurrent_activities=10,
        ) as running:
            yield running
