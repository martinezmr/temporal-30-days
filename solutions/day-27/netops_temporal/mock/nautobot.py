"""Fake Nautobot for LAB_MODE=mock: the same intent lab/nautobot/seed.py creates."""

import json

from netops_temporal.constants import device_address
from netops_temporal.mock.devices import FIXTURES


def device_intent(device: str) -> dict:
    """{"device", "role", "location", "target_version"} for one device."""
    device_address(device)
    return json.loads((FIXTURES / "nautobot" / "intent.json").read_text())[device]
