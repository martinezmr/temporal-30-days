"""One place to connect to Temporal, so the worker and every starter use the same data converter."""

import base64
import dataclasses
import os
from collections.abc import Sequence

from temporalio.client import Client, Interceptor
from temporalio.converter import DataConverter
from temporalio.runtime import Runtime

from netops_temporal.codec import EncryptionCodec
from netops_temporal.constants import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE
from netops_temporal.llm.agent_models import agents_plugin


def data_converter() -> DataConverter:
    """Pydantic for models (Day 3), plus encryption when PAYLOAD_KEY is set (Day 21).

    Day 26: the OpenAI Agents plugin (added in connect) needs its own payload converter, which
    handles Pydantic models like Day 3's, and the Agents SDK's types too. It swaps it in when
    the client starts with the default one, so that's what this returns.
    """
    key = os.environ.get("PAYLOAD_KEY")
    if not key:
        return DataConverter.default
    return dataclasses.replace(
        DataConverter.default, payload_codec=EncryptionCodec(base64.b64decode(key))
    )


async def connect(
    runtime: Runtime | None = None,
    interceptors: Sequence[Interceptor] = (),
    namespace: str = TEMPORAL_NAMESPACE,
) -> Client:
    # The Pydantic converter turns models into JSON payloads and back. Worker and starters
    # must agree on it, or one side can't read what the other wrote. From Day 21 that includes
    # the encryption key: a starter without PAYLOAD_KEY can't read an encrypted result.
    # Day 20: the worker can pass a runtime (metrics) and interceptors (tracing).
    # Day 22: the compliance worker connects to its own namespace.
    return await Client.connect(
        TEMPORAL_ADDRESS,
        namespace=namespace,
        data_converter=data_converter(),
        runtime=runtime,
        interceptors=interceptors,
        # Day 26: runs the troubleshooting agent's model calls as activities.
        plugins=[agents_plugin()],
    )
