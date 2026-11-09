"""Day 17: change device config with NAPALM, and undo it.

NAPALM's EOS driver uses an EOS config session: load_merge_candidate stages the lines,
compare_config shows the real diff, commit_config applies it (after saving the current startup
config to flash:rollback-0), and rollback() puts flash:rollback-0 back. That's a saga built
into the device: every step has an undo.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pyeapi.eapilib
from napalm import get_network_driver
from napalm.base.exceptions import ConnectionException

from netops_temporal.constants import DEVICE_PASSWORD, DEVICE_USERNAME, device_address, lab_mode
from netops_temporal.devices.errors import DeviceAuthError, DeviceUnreachableError
from netops_temporal.mock import devices as mock_devices


@contextmanager
def _driver(device: str) -> Iterator:
    address = device_address(device)
    driver = get_network_driver("eos")(
        hostname=address.host,
        username=DEVICE_USERNAME,
        password=DEVICE_PASSWORD,
        timeout=30,
        optional_args={"transport": "https", "port": address.eapi_port},
    )
    # Same error translation as napalm_eos.py: the driver connects lazily.
    try:
        driver.open()
        try:
            yield driver
        finally:
            driver.close()
    except (ConnectionException, pyeapi.eapilib.ConnectionError) as err:
        if "Unauthorized" in str(err):
            raise DeviceAuthError(f"{device}: {err}") from err
        raise DeviceUnreachableError(f"{device}: {err}") from err


def push_lines(device: str, lines: list[str]) -> str:
    """Merge `lines` into the running config. Returns the diff; empty means nothing changed."""
    if lab_mode() == "mock":
        return mock_devices.push_lines(device, lines)
    with _driver(device) as driver:
        driver.load_merge_candidate(config="\n".join(lines))
        diff = driver.compare_config()
        if diff:
            driver.commit_config()
        else:
            driver.discard_config()  # nothing to do: don't leave a session open
        return diff


def rollback(device: str) -> None:
    """Undo the last NAPALM commit on this device."""
    if lab_mode() == "mock":
        return mock_devices.rollback(device)
    with _driver(device) as driver:
        driver.rollback()
