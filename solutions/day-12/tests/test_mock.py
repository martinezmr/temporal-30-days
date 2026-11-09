import pytest

from netops_temporal.constants import DEVICES, SHOW_TECH_COMMANDS
from netops_temporal.devices.errors import DeviceAuthError, DeviceUnreachableError
from netops_temporal.mock import devices, nautobot


def test_show_version_fixture():
    [version] = devices.show("bos-rtr-01", ["show version"])
    assert version["modelName"] == "cEOSLab"
    assert version["version"].startswith("4.32.0F")


def test_show_returns_one_result_per_command():
    results = devices.show("nyc-acc-01", ["show version", "show lldp neighbors"])
    assert len(results) == 2
    assert "lldpNeighbors" in results[1]


def test_show_unknown_command_explains_missing_fixture():
    with pytest.raises(ValueError, match="no mock fixture"):
        devices.show("bos-rtr-01", ["show bgp summary"])


def test_unreachable_injection(monkeypatch):
    monkeypatch.setenv("MOCK_UNREACHABLE", "bos-rtr-01")
    with pytest.raises(DeviceUnreachableError):
        devices.show("bos-rtr-01", ["show version"])
    assert devices.show("bos-acc-01", ["show version"])


def test_auth_fail_injection(monkeypatch):
    monkeypatch.setenv("MOCK_AUTH_FAIL", "1")
    with pytest.raises(DeviceAuthError):
        devices.running_config("bos-rtr-01")


def test_running_config_is_lab_startup_config():
    assert "hostname nyc-acc-01" in devices.running_config("nyc-acc-01")


def test_intent_drift_fixture():
    versions = {d: nautobot.device_intent(d)["target_version"] for d in DEVICES}
    assert versions == {
        "bos-rtr-01": "4.32.0F",
        "bos-acc-01": "4.32.0F",
        "nyc-rtr-01": "4.32.0F",
        "nyc-acc-01": "4.33.1F",
    }
    assert nautobot.device_intent("bos-acc-01")["role"] == "access"
    assert nautobot.device_intent("nyc-rtr-01")["location"] == "NYC"


def test_cli_returns_ten_distinct_outputs():
    outputs = [devices.cli("bos-rtr-01", cmd) for cmd in SHOW_TECH_COMMANDS]
    assert len(SHOW_TECH_COMMANDS) == 10
    assert all(outputs)
    assert len(set(outputs)) == 10


def test_cli_delay(monkeypatch):
    slept = []
    monkeypatch.setattr(devices.time, "sleep", slept.append)
    monkeypatch.setenv("MOCK_CLI_DELAY", "2.5")
    devices.cli("bos-rtr-01", SHOW_TECH_COMMANDS[0])
    assert slept == [2.5]
