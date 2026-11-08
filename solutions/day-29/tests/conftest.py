"""Shared test setup: mock lab on, a time-skipping Temporal server, and a worker for it."""

import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import pytest
from temporalio.api.enums.v1 import IndexedValueType
from temporalio.api.nexus.v1 import EndpointSpec, EndpointTarget
from temporalio.api.operatorservice.v1 import AddSearchAttributesRequest, CreateNexusEndpointRequest
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from netops_temporal.activities import backup, show_tech
from netops_temporal.constants import (
    COMPLIANCE_ENDPOINT,
    COMPLIANCE_NAMESPACE,
    COMPLIANCE_TASK_QUEUE,
    DEVICE_IO_TASK_QUEUE,
)
from netops_temporal.observability import COMPLIANCE_SA, DEVICE_SA
from netops_temporal.workers.compliance import compliance_worker, remediation_activity_worker
from netops_temporal.workers.main import ACTIVITIES, WORKFLOWS

TASK_QUEUE = "test"


@pytest.fixture(autouse=True)
def mock_lab(monkeypatch, tmp_path):
    """Every test runs against the mock lab, with outputs in a throwaway directory."""
    monkeypatch.setenv("LAB_MODE", "mock")
    # Day 14: the mock lab keeps pushed config in OUTPUT_DIR/mock-state.json.
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    for name in ("MOCK_UNREACHABLE", "MOCK_AUTH_FAIL", "MOCK_CLI_DELAY", "MOCK_VERIFY_FAIL"):
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
        # Day 20: the workflows set search attributes, and a server rejects unknown ones.
        await register_search_attributes(env.client, env.client.namespace)
        # Day 22: the orchestrator calls the compliance endpoint. Here it points at the same
        # namespace (the test server has only one); nexus_env below uses a real second one.
        await create_compliance_endpoint(env.client, env.client.namespace)
        yield env


async def register_search_attributes(client: Client, namespace: str) -> None:
    await client.operator_service.add_search_attributes(
        AddSearchAttributesRequest(
            namespace=namespace,
            search_attributes={
                key.name: IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD
                for key in (DEVICE_SA, COMPLIANCE_SA)
            },
        )
    )


async def create_compliance_endpoint(client: Client, target_namespace: str) -> None:
    """What lab/nexus-endpoint.sh does: route `compliance-endpoint` to the compliance task
    queue in `target_namespace`."""
    await client.operator_service.create_nexus_endpoint(
        CreateNexusEndpointRequest(
            spec=EndpointSpec(
                name=COMPLIANCE_ENDPOINT,
                target=EndpointTarget(
                    worker=EndpointTarget.Worker(
                        namespace=target_namespace, task_queue=COMPLIANCE_TASK_QUEUE
                    )
                ),
            )
        )
    )


@asynccontextmanager
async def workers(client, compliance_client=None):
    """Like workers/main.py: workflows on TASK_QUEUE, and (Day 21) activities on the device-io
    queue, where every workflow sends them. Plus (Days 22-23) the compliance team's workers, in
    their own namespace when there is one. Yields the workflow worker."""
    with ThreadPoolExecutor(max_workers=10) as executor:
        async with (
            Worker(client, task_queue=TASK_QUEUE, workflows=WORKFLOWS) as running,
            Worker(
                client,
                task_queue=DEVICE_IO_TASK_QUEUE,
                activities=ACTIVITIES,
                activity_executor=executor,
                max_concurrent_activities=10,
            ),
        ):
            # Day 23: the compliance team's workers run the remediation workflow and its
            # activities too.
            if compliance_client is None:
                # One namespace: the device-io worker above already serves those activities.
                async with compliance_worker(client):
                    yield running
            else:
                async with (
                    compliance_worker(compliance_client),
                    remediation_activity_worker(compliance_client, executor),
                ):
                    yield running


@pytest.fixture
def start_workers():
    """Day 25: the workers() context manager itself, for tests that stop the workers and start
    new ones in the middle."""
    return workers


@pytest.fixture
async def worker(workflow_env):
    """Workers with the same workflows and activities as the real one."""
    async with workers(workflow_env.client) as running:
        yield running


@pytest.fixture
async def dev_env():
    """A real Temporal dev server, for the few features the time-skipping server doesn't
    implement faithfully (Day 15: parent close policies). Uses the `temporal` CLI if it's
    installed, otherwise downloads the dev server once."""
    async with await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter,
        dev_server_existing_path=shutil.which("temporal"),
        # Day 20: the same search attributes lab/start-temporal.sh registers.
        search_attributes=[DEVICE_SA, COMPLIANCE_SA],
    ) as env:
        await create_compliance_endpoint(env.client, env.client.namespace)
        yield env


@pytest.fixture
async def dev_worker(dev_env):
    async with workers(dev_env.client) as running:
        yield running


@pytest.fixture
async def nexus_env():
    """Day 22: a real dev server with two namespaces, like the course lab: the orchestrator in
    `default`, the compliance team in `compliance`, and the endpoint between them."""
    async with await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter,
        dev_server_existing_path=shutil.which("temporal"),
        search_attributes=[DEVICE_SA, COMPLIANCE_SA],
        dev_server_extra_args=["--namespace", COMPLIANCE_NAMESPACE],
    ) as env:
        # search_attributes= above registers them in `default` only. Day 23's remediation
        # sets them in `compliance` (lab/nexus-endpoint.sh does the same for the lab).
        await register_search_attributes(env.client, COMPLIANCE_NAMESPACE)
        await create_compliance_endpoint(env.client, COMPLIANCE_NAMESPACE)
        yield env


@pytest.fixture
async def nexus_workers(nexus_env):
    compliance_client = Client(**{**nexus_env.client.config(), "namespace": COMPLIANCE_NAMESPACE})
    async with workers(nexus_env.client, compliance_client) as running:
        yield running
