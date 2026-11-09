"""Read device intent from Nautobot with pynautobot."""

import pynautobot

from netops_temporal.constants import NAUTOBOT_TOKEN, NAUTOBOT_URL, device_address, lab_mode
from netops_temporal.devices.errors import UnknownDeviceError
from netops_temporal.mock import nautobot as mock_nautobot
from netops_temporal.models import DeviceIntent


def get_device_intent(device: str) -> DeviceIntent:
    """Role, location and target EOS version for one device, as recorded in Nautobot."""
    if lab_mode() == "mock":
        return DeviceIntent(**mock_nautobot.device_intent(device))

    device_address(device)  # unknown names fail fast, before any API call
    api = pynautobot.api(NAUTOBOT_URL, token=NAUTOBOT_TOKEN)
    # depth=1 returns role and location with their names, not just their IDs.
    record = api.dcim.devices.get(name=device, depth=1)
    if record is None:
        raise UnknownDeviceError(f"{device} is in DEVICE_HOSTS but not in Nautobot")
    return DeviceIntent(
        device=device,
        role=record.role.name,
        location=record.location.name,
        target_version=record.custom_fields["target_version"],
    )
