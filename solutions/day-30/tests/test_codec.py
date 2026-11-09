"""Day 21: payloads are encrypted before they leave the worker or the starter."""

import dataclasses
import os
import uuid

import pytest
from temporalio.api.common.v1 import Payload
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from netops_temporal.codec import EncryptionCodec
from netops_temporal.models import FactsRequest
from netops_temporal.workflows.facts import GetFactsWorkflow

KEY = os.urandom(32)


async def test_codec_roundtrip():
    codec = EncryptionCodec(KEY)
    original = [Payload(metadata={"encoding": b"json/plain"}, data=b'{"device":"bos-rtr-01"}')]
    encoded = await codec.encode(original)
    assert encoded[0].metadata["encoding"] == b"binary/encrypted"
    assert b"bos-rtr-01" not in encoded[0].data
    assert await codec.decode(encoded) == original


async def test_codec_refuses_a_different_key():
    encoded = await EncryptionCodec(KEY).encode([Payload(data=b"secret")])
    with pytest.raises(ValueError, match="key"):
        await EncryptionCodec(os.urandom(32), key_id="other").decode(encoded)


def with_codec(client: Client, codec: EncryptionCodec | None) -> Client:
    converter = dataclasses.replace(pydantic_data_converter, payload_codec=codec)
    return Client(**{**client.config(), "data_converter": converter})


async def raw_history_bytes(client: Client, workflow_id: str) -> bytes:
    history = await client.get_workflow_handle(workflow_id).fetch_history()
    return b"".join(e.SerializeToString() for e in history.events)


async def run_facts(env, worker, client: Client) -> str:
    workflow_id = f"facts-{uuid.uuid4()}"
    facts = await client.execute_workflow(
        GetFactsWorkflow.run,
        FactsRequest(device="bos-rtr-01"),
        id=workflow_id,
        task_queue=worker.task_queue,
    )
    assert facts.facts.device == "bos-rtr-01"  # the starter, with the key, reads it fine
    return workflow_id


async def test_encrypted_payload_unreadable_in_history(workflow_env, codec_worker):
    client = with_codec(workflow_env.client, EncryptionCodec(KEY))
    workflow_id = await run_facts(workflow_env, codec_worker, client)
    # What the server stores: no device name anywhere in the payloads.
    assert b"bos-rtr-01" not in await raw_history_bytes(workflow_env.client, workflow_id)


async def test_plain_payload_readable_in_history(workflow_env, worker):
    """The control for the test above: without the codec, the server sees everything."""
    workflow_id = await run_facts(workflow_env, worker, workflow_env.client)
    assert b"bos-rtr-01" in await raw_history_bytes(workflow_env.client, workflow_id)


@pytest.fixture
async def codec_worker(workflow_env):
    from concurrent.futures import ThreadPoolExecutor

    from temporalio.worker import Worker

    from netops_temporal.constants import DEVICE_IO_TASK_QUEUE
    from netops_temporal.workers.main import ACTIVITIES, WORKFLOWS

    client = with_codec(workflow_env.client, EncryptionCodec(KEY))
    with ThreadPoolExecutor(max_workers=2) as pool:
        async with (
            Worker(client, task_queue="codec", workflows=WORKFLOWS) as wf_worker,
            Worker(
                client,
                task_queue=DEVICE_IO_TASK_QUEUE,
                activities=ACTIVITIES,
                activity_executor=pool,
                max_concurrent_activities=2,
            ),
        ):
            yield wf_worker


async def test_codec_server_decodes_for_the_ui(aiohttp_client_session):
    """The UI posts encrypted payloads to the codec server and shows what comes back."""
    from google.protobuf import json_format
    from temporalio.api.common.v1 import Payloads

    from netops_temporal.tools.codec_server import make_app

    codec = EncryptionCodec(KEY)
    original = Payload(metadata={"encoding": b"json/plain"}, data=b'"bos-rtr-01"')
    encrypted = Payloads(payloads=await codec.encode([original]))
    client = await aiohttp_client_session(make_app(codec))
    response = await client.post("/decode", data=json_format.MessageToJson(encrypted))
    assert response.status == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:8233"
    decoded = json_format.Parse(await response.text(), Payloads())
    assert list(decoded.payloads) == [original]


@pytest.fixture
async def aiohttp_client_session():
    from aiohttp.test_utils import TestClient, TestServer

    clients = []

    async def make(app):
        client = TestClient(TestServer(app))
        await client.start_server()
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.close()
