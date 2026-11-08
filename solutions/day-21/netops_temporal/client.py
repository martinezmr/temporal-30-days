"""One place to connect to Temporal, so the worker and every starter use the same data converter."""

import base64
import dataclasses
import os
from collections.abc import Sequence

from temporalio.client import Client, Interceptor
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.converter import DataConverter
from temporalio.runtime import Runtime

from netops_temporal.codec import EncryptionCodec
from netops_temporal.constants import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE


def data_converter() -> DataConverter:
    """Pydantic for models (Day 3), plus encryption when PAYLOAD_KEY is set (Day 21)."""
    key = os.environ.get("PAYLOAD_KEY")
    if not key:
        return pydantic_data_converter
    return dataclasses.replace(
        pydantic_data_converter, payload_codec=EncryptionCodec(base64.b64decode(key))
    )


async def connect(
    runtime: Runtime | None = None, interceptors: Sequence[Interceptor] = ()
) -> Client:
    # The Pydantic converter turns models into JSON payloads and back. Worker and starters
    # must agree on it, or one side can't read what the other wrote. From Day 21 that includes
    # the encryption key: a starter without PAYLOAD_KEY can't read an encrypted result.
    # Day 20: the worker can pass a runtime (metrics) and interceptors (tracing).
    return await Client.connect(
        TEMPORAL_ADDRESS,
        namespace=TEMPORAL_NAMESPACE,
        data_converter=data_converter(),
        runtime=runtime,
        interceptors=interceptors,
    )
