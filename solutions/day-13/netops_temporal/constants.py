"""Shared names and settings, read from the environment (see .env.example)."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from netops_temporal.devices.errors import UnknownDeviceError

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")

# Task queues. Workers poll a queue by name; starters send work to it by the same name.
# Everything runs on the orchestration queue until Day 21 splits device I/O onto its own.
ORCHESTRATION_TASK_QUEUE = "netops-orchestration"
DEVICE_IO_TASK_QUEUE = "netops-device-io"

DEVICE_USERNAME = os.environ.get("DEVICE_USERNAME", "admin")
DEVICE_PASSWORD = os.environ.get("DEVICE_PASSWORD", "admin")

NAUTOBOT_URL = os.environ.get("NAUTOBOT_URL", "http://localhost:8080")
NAUTOBOT_TOKEN = os.environ.get("NAUTOBOT_TOKEN", "")

# Big outputs (config backups, show tech) are written here; workflows only see file paths.
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output"))

# The commands Day 5's show-tech collection runs, one at a time.
SHOW_TECH_COMMANDS = [
    "show version",
    "show interfaces status",
    "show ip interface brief",
    "show ip route",
    "show ip ospf neighbor",
    "show lldp neighbors",
    "show logging 50",
    "show processes top once",
    "show running-config",
    "show inventory",
]


@dataclass(frozen=True)
class DeviceAddress:
    """Where to reach one device. Ports change from the defaults when you tunnel via a jump host."""

    host: str
    eapi_port: int = 443
    ssh_port: int = 22


# The static management IPs from lab/ceos-clab.clab.yml.
DEFAULT_DEVICE_HOSTS = (
    "bos-rtr-01=172.20.20.2,bos-acc-01=172.20.20.3,nyc-rtr-01=172.20.20.4,nyc-acc-01=172.20.20.5"
)


def parse_device_hosts(raw: str) -> dict[str, DeviceAddress]:
    """Parse "name=host[:eapi_port[:ssh_port]],..." into {name: DeviceAddress}."""
    hosts: dict[str, DeviceAddress] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        name, sep, target = pair.partition("=")
        parts = target.strip().split(":")
        if not sep or not name.strip() or not parts[0] or len(parts) > 3:
            raise ValueError(
                f"DEVICE_HOSTS entry {pair!r} should look like "
                "name=host or name=host:eapi_port:ssh_port"
            )
        try:
            ports = [int(p) for p in parts[1:]]
        except ValueError:
            raise ValueError(
                f"DEVICE_HOSTS entry {pair!r} has a port that isn't a number"
            ) from None
        hosts[name.strip()] = DeviceAddress(parts[0], *ports)
    return hosts


DEVICE_HOSTS = parse_device_hosts(os.environ.get("DEVICE_HOSTS") or DEFAULT_DEVICE_HOSTS)
DEVICES = list(DEVICE_HOSTS)


def device_address(device: str) -> DeviceAddress:
    try:
        return DEVICE_HOSTS[device]
    except KeyError:
        raise UnknownDeviceError(
            f"unknown device {device!r}; DEVICE_HOSTS knows {', '.join(DEVICES)}"
        ) from None


def lab_mode() -> Literal["live", "mock"]:
    """ "live" talks to real devices and Nautobot; "mock" replays fixtures. Read on every call
    so tests (and a restarted worker) pick up changes."""
    mode = os.environ.get("LAB_MODE", "live")
    if mode not in ("live", "mock"):
        raise ValueError(f"LAB_MODE must be 'live' or 'mock', not {mode!r}")
    return mode
