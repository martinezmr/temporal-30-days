"""Fake devices for LAB_MODE=mock: real outputs captured from the lab, plus failure switches.

    MOCK_UNREACHABLE=bos-rtr-01,nyc-rtr-01   those devices act as if they're down
    MOCK_AUTH_FAIL=1                          every device rejects the login
    MOCK_CLI_DELAY=3                          each CLI command takes 3 seconds

The switches are read on every call, so a test (or a restarted worker) sees changes.
"""

import json
import os
import time
from pathlib import Path

from netops_temporal.constants import SHOW_TECH_COMMANDS, device_address
from netops_temporal.devices.errors import DeviceAuthError, DeviceUnreachableError
from netops_temporal.mock import state as mock_state

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _connect(device: str) -> None:
    """Behave like opening a connection: unknown names, downed devices and bad logins fail here."""
    device_address(device)
    unreachable = {d.strip() for d in os.environ.get("MOCK_UNREACHABLE", "").split(",")}
    if device in unreachable:
        raise DeviceUnreachableError(f"{device} is unreachable (MOCK_UNREACHABLE)")
    if os.environ.get("MOCK_AUTH_FAIL") == "1":
        raise DeviceAuthError(f"{device} rejected the login (MOCK_AUTH_FAIL)")


def show(device: str, commands: list[str]) -> list[dict]:
    """Like eAPI runCmds with JSON output: one result dict per command."""
    _connect(device)
    outputs = json.loads((FIXTURES / "eapi" / f"{device}.json").read_text())
    missing = [c for c in commands if c not in outputs]
    if missing:
        raise ValueError(f"no mock fixture for {missing} on {device}; available: {sorted(outputs)}")
    return [outputs[c] for c in commands]


def cli(device: str, command: str) -> str:
    """Like sending one command over SSH and reading the text that comes back."""
    _connect(device)
    if command not in SHOW_TECH_COMMANDS:
        raise ValueError(f"no mock fixture for {command!r}; available: {SHOW_TECH_COMMANDS}")
    time.sleep(float(os.environ.get("MOCK_CLI_DELAY") or 0))
    number = SHOW_TECH_COMMANDS.index(command) + 1
    return (FIXTURES / "cli" / "show_tech" / f"{number:02d}.txt").read_text()


def running_config(device: str) -> str:
    _connect(device)
    config = (FIXTURES / "configs" / f"{device}.cfg").read_text()
    # Day 14: lines "pushed" to the mock device are part of its config from then on.
    pushed = mock_state.applied_lines(device)
    return config + "".join(f"{line}\n" for line in pushed)
