"""Read device config with NAPALM.

NAPALM gives the same functions (get_config, get_facts, load/compare/commit) across vendors.
Its EOS driver talks eAPI through pyeapi under the hood, so it uses the eAPI port. Day 17 uses
NAPALM's candidate/commit/rollback for a safe config push.
"""

import pyeapi.eapilib
from napalm import get_network_driver
from napalm.base.exceptions import ConnectionException

from netops_temporal.constants import DEVICE_PASSWORD, DEVICE_USERNAME, device_address, lab_mode
from netops_temporal.devices.errors import DeviceAuthError, DeviceUnreachableError
from netops_temporal.mock import devices as mock_devices


def get_running_config(device: str) -> str:
    if lab_mode() == "mock":
        return mock_devices.running_config(device)

    address = device_address(device)
    driver = get_network_driver("eos")(
        hostname=address.host,
        username=DEVICE_USERNAME,
        password=DEVICE_PASSWORD,
        timeout=10,
        optional_args={"transport": "https", "port": address.eapi_port},
    )
    # The EOS driver connects lazily: open() can succeed and the first real call fail.
    # So translate errors from both, whether NAPALM wrapped them or not.
    try:
        driver.open()
        try:
            return driver.get_config(retrieve="running")["running"]
        finally:
            driver.close()
    except (ConnectionException, pyeapi.eapilib.ConnectionError) as err:
        if "Unauthorized" in str(err):
            raise DeviceAuthError(f"{device}: {err}") from err
        raise DeviceUnreachableError(f"{device}: {err}") from err
