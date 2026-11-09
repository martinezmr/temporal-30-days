"""Send CLI commands over SSH with Netmiko.

Netmiko logs in like a person would, sends a command, and reads the screen until the prompt
comes back. It's slow and blocking, which is exactly why Day 5 uses it.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from netmiko import ConnectHandler, NetmikoAuthenticationException, NetmikoTimeoutException

from netops_temporal.constants import DEVICE_PASSWORD, DEVICE_USERNAME, device_address, lab_mode
from netops_temporal.devices.errors import DeviceAuthError, DeviceUnreachableError
from netops_temporal.mock import devices as mock_devices


@contextmanager
def cli_session(device: str) -> Iterator[Callable[[str], str]]:
    """Open one SSH session and yield a `send(command) -> output` function.

    with cli_session("bos-rtr-01") as send:
        print(send("show version"))
    """
    if lab_mode() == "mock":
        yield lambda command: mock_devices.cli(device, command)
        return

    address = device_address(device)
    try:
        conn = ConnectHandler(
            device_type="arista_eos",
            host=address.host,
            port=address.ssh_port,
            username=DEVICE_USERNAME,
            password=DEVICE_PASSWORD,
            conn_timeout=10,
        )
    except NetmikoAuthenticationException as err:
        raise DeviceAuthError(f"{device}: {err}") from err
    except (NetmikoTimeoutException, OSError) as err:
        raise DeviceUnreachableError(f"{device}: {err}") from err
    try:
        conn.enable()
        yield lambda command: conn.send_command(command, read_timeout=60)
    finally:
        conn.disconnect()
