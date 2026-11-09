"""One place to connect to Temporal, so the worker and every starter use the same data converter."""

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from netops_temporal.constants import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE


async def connect() -> Client:
    # The Pydantic converter turns models into JSON payloads and back. Worker and starters
    # must agree on it, or one side can't read what the other wrote.
    return await Client.connect(
        TEMPORAL_ADDRESS,
        namespace=TEMPORAL_NAMESPACE,
        data_converter=pydantic_data_converter,
    )
