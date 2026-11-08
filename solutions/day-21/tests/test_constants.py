import pytest

from netops_temporal.constants import (
    DEVICES,
    DeviceAddress,
    device_address,
    lab_mode,
    parse_device_hosts,
)
from netops_temporal.devices.errors import UnknownDeviceError


def test_parse_device_hosts_basic():
    assert parse_device_hosts("a=1.1.1.1, b=2.2.2.2") == {
        "a": DeviceAddress("1.1.1.1"),
        "b": DeviceAddress("2.2.2.2"),
    }


def test_parse_device_hosts_default_ports():
    address = parse_device_hosts("a=1.1.1.1")["a"]
    assert (address.eapi_port, address.ssh_port) == (443, 22)


def test_parse_device_hosts_with_ports():
    assert parse_device_hosts("a=127.0.0.1:8441:2201,b=127.0.0.1:8442") == {
        "a": DeviceAddress("127.0.0.1", eapi_port=8441, ssh_port=2201),
        "b": DeviceAddress("127.0.0.1", eapi_port=8442, ssh_port=22),
    }


def test_parse_device_hosts_ignores_empty_segments():
    assert parse_device_hosts("a=1.1.1.1,,") == {"a": DeviceAddress("1.1.1.1")}


def test_parse_device_hosts_rejects_malformed():
    with pytest.raises(ValueError, match=r"a1\.1\.1\.1.*DEVICE_HOSTS|DEVICE_HOSTS.*a1\.1\.1\.1"):
        parse_device_hosts("a1.1.1.1")


def test_parse_device_hosts_rejects_bad_port():
    with pytest.raises(ValueError, match="DEVICE_HOSTS"):
        parse_device_hosts("a=1.1.1.1:https")


def test_default_inventory_is_the_four_lab_devices():
    assert DEVICES == ["bos-rtr-01", "bos-acc-01", "nyc-rtr-01", "nyc-acc-01"]


def test_device_address_unknown_lists_known():
    with pytest.raises(UnknownDeviceError, match="bos-rtr-01"):
        device_address("nope")


def test_lab_mode_reads_env_each_call(monkeypatch):
    monkeypatch.setenv("LAB_MODE", "mock")
    assert lab_mode() == "mock"
    monkeypatch.delenv("LAB_MODE")
    assert lab_mode() == "live"
    monkeypatch.setenv("LAB_MODE", "bogus")
    with pytest.raises(ValueError, match="LAB_MODE"):
        lab_mode()
