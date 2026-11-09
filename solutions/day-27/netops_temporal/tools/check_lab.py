"""Check that everything the course talks to is reachable from here.

    uv run --env-file .env python -m netops_temporal.tools.check_lab

Checks Temporal, eAPI and SSH on every device in DEVICE_HOSTS, and the Nautobot API.
In mock mode only Temporal is checked; devices and Nautobot are replayed from fixtures.
"""

import asyncio
import socket
import sys
from dataclasses import dataclass

import pyeapi
import requests
from temporalio.client import Client

from netops_temporal.constants import (
    DEVICE_HOSTS,
    DEVICE_PASSWORD,
    DEVICE_USERNAME,
    NAUTOBOT_TOKEN,
    NAUTOBOT_URL,
    TEMPORAL_ADDRESS,
    TEMPORAL_NAMESPACE,
    DeviceAddress,
    lab_mode,
)

NETWORKING_HINT = (
    "Devices unreachable from this machine? See docs/lab-setup.md#macos-networking "
    "(tunnels through a jump host, sshuttle, or running the worker on the lab VM)."
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def check_temporal() -> CheckResult:
    async def connect() -> None:
        await asyncio.wait_for(Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE), 5)

    try:
        asyncio.run(connect())
        return CheckResult("temporal", True, TEMPORAL_ADDRESS)
    except Exception as err:
        return CheckResult("temporal", False, f"{TEMPORAL_ADDRESS}: {err or type(err).__name__}")


def check_eapi(device: str, address: DeviceAddress) -> CheckResult:
    name = f"{device} eAPI"
    try:
        node = pyeapi.connect(
            transport="https",
            host=address.host,
            port=address.eapi_port,
            username=DEVICE_USERNAME,
            password=DEVICE_PASSWORD,
            timeout=5,
            return_node=True,
        )
        version = node.run_commands(["show version"])[0]["version"]
        return CheckResult(name, True, f"{address.host}:{address.eapi_port} EOS {version}")
    except Exception as err:
        return CheckResult(name, False, f"{address.host}:{address.eapi_port}: {err}")


def check_ssh(device: str, address: DeviceAddress) -> CheckResult:
    name = f"{device} SSH"
    try:
        with socket.create_connection((address.host, address.ssh_port), timeout=5):
            return CheckResult(name, True, f"{address.host}:{address.ssh_port} open")
    except OSError as err:
        return CheckResult(name, False, f"{address.host}:{address.ssh_port}: {err}")


def check_nautobot() -> CheckResult:
    try:
        response = requests.get(
            f"{NAUTOBOT_URL}/api/status/",
            headers={"Authorization": f"Token {NAUTOBOT_TOKEN}"},
            timeout=5,
        )
        response.raise_for_status()
        version = response.json().get("nautobot-version")
        return CheckResult("nautobot", True, f"{NAUTOBOT_URL} Nautobot {version}")
    except Exception as err:
        return CheckResult("nautobot", False, f"{NAUTOBOT_URL}: {err}")


def run_checks() -> list[CheckResult]:
    results = [check_temporal()]
    if lab_mode() == "mock":
        for device in DEVICE_HOSTS:
            results += [
                CheckResult(f"{device} eAPI", True, "mock mode"),
                CheckResult(f"{device} SSH", True, "mock mode"),
            ]
        results.append(CheckResult("nautobot", True, "mock mode"))
        return results
    for device, address in DEVICE_HOSTS.items():
        results += [check_eapi(device, address), check_ssh(device, address)]
    results.append(check_nautobot())
    return results


def main() -> int:
    results = run_checks()
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"{'OK  ' if r.ok else 'FAIL'}  {r.name:<{width}}  {r.detail}")
    if any(not r.ok and r.name not in ("temporal", "nautobot") for r in results):
        print()
        print(NETWORKING_HINT)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
