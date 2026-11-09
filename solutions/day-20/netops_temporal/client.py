"""One place to connect to Temporal, so the worker and every starter use the same data converter."""

from collections.abc import Sequence

from temporalio.client import Client, Interceptor
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.runtime import Runtime

from netops_temporal.constants import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE


async def connect(
    runtime: Runtime | None = None, interceptors: Sequence[Interceptor] = ()
) -> Client:
    # The Pydantic converter turns models into JSON payloads and back. Worker and starters
    # must agree on it, or one side can't read what the other wrote.
    # Day 20: the worker can pass a runtime (metrics) and interceptors (tracing).
    return await Client.connect(
        TEMPORAL_ADDRESS,
        namespace=TEMPORAL_NAMESPACE,
        data_converter=pydantic_data_converter,
        runtime=runtime,
        interceptors=interceptors,
    )
