"""Run show commands over eAPI with pyeapi.

pyeapi is Arista's Python client for eAPI, the JSON-RPC API EOS serves over HTTPS. pyeapi's
`Node.run_commands()` sends a list of commands and returns one parsed JSON result per command.
We wrap it as `run_show()` so the rest of the code doesn't care whether it's talking to a real
device or to the mock lab.
"""

import pyeapi
import pyeapi.eapilib

from netops_temporal.constants import DEVICE_PASSWORD, DEVICE_USERNAME, device_address, lab_mode
from netops_temporal.devices.errors import DeviceAuthError, DeviceUnreachableError
from netops_temporal.mock import devices as mock_devices


def run_show(device: str, commands: list[str]) -> list[dict]:
    """Run show commands on one device; returns one JSON result dict per command."""
    if lab_mode() == "mock":
        return mock_devices.show(device, commands)

    address = device_address(device)
    node = pyeapi.connect(
        transport="https",
        host=address.host,
        port=address.eapi_port,
        username=DEVICE_USERNAME,
        password=DEVICE_PASSWORD,
        timeout=10,
        return_node=True,
    )
    try:
        return node.run_commands(commands)
    except pyeapi.eapilib.ConnectionError as err:
        # pyeapi raises the same ConnectionError for "can't connect" and "bad password";
        # only the message tells them apart. Translate both into our own error types.
        if err.message.startswith("Unauthorized"):
            raise DeviceAuthError(f"{device}: {err.message}") from err
        raise DeviceUnreachableError(f"{device}: {err.message}") from err
