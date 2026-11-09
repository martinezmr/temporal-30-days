"""Fake devices for LAB_MODE=mock: real outputs captured from the lab, plus failure switches.

    MOCK_UNREACHABLE=bos-rtr-01,nyc-rtr-01   those devices act as if they're down
    MOCK_AUTH_FAIL=1                          every device rejects the login
    MOCK_CLI_DELAY=3                          each CLI command (and, from Day 17, each
                                              config read) takes 3 seconds
    MOCK_VERIFY_FAIL=bos-acc-01               (Day 17) pushes to those devices "don't stick":
                                              the running config never shows them

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
    time.sleep(float(os.environ.get("MOCK_CLI_DELAY") or 0))
    # Some fixtures don't end with a newline: add one, so pushed lines start on their own line.
    config = (FIXTURES / "configs" / f"{device}.cfg").read_text().rstrip("\n") + "\n"
    if device in _devices_in("MOCK_VERIFY_FAIL"):
        return config
    # Day 14: lines "pushed" to the mock device are part of its config from then on.
    pushed = mock_state.applied_lines(device)
    return config + "".join(f"{line}\n" for line in pushed)


def push_lines(device: str, lines: list[str]) -> str:
    """Day 17: like NAPALM merge + compare + commit. Returns the diff; empty means no change."""
    _connect(device)
    present = set(mock_state.applied_lines(device))
    new = [line for line in lines if line not in present]
    if new:
        mock_state.apply_lines(device, new)
    return "\n".join(f"+{line}" for line in new)


def rollback(device: str) -> None:
    """Day 17: like NAPALM rollback: undo the last commit."""
    _connect(device)
    mock_state.rollback(device)


def _devices_in(variable: str) -> set[str]:
    return {d.strip() for d in os.environ.get(variable, "").split(",") if d.strip()}
