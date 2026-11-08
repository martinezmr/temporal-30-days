"""Day 14: drift detection is a pure function, so it's tested without Temporal at all."""

from netops_temporal.drift import compute_drift
from netops_temporal.models import DeviceFacts, DeviceIntent, DriftReport
from netops_temporal.policies import POLICIES

INTENT = DeviceIntent(device="nyc-acc-01", role="access", location="NYC", target_version="4.33.1F")


def test_policies_cover_both_roles():
    assert POLICIES["access"] == ["ntp server 192.0.2.10"]
    assert POLICIES["router"] == ["ntp server 192.0.2.10", "logging host 192.0.2.50"]


def test_compute_drift_version_and_config():
    facts = DeviceFacts(device="nyc-acc-01", model="cEOSLab", version="4.32.0F")
    drift = compute_drift(INTENT, facts, ["ntp server 192.0.2.10"])
    assert drift == [
        DriftReport(device="nyc-acc-01", kind="version", expected="4.33.1F", actual="4.32.0F"),
        DriftReport(
            device="nyc-acc-01",
            kind="config",
            expected="1 policy line(s) present",
            actual="1 missing",
            missing_lines=["ntp server 192.0.2.10"],
        ),
    ]


def test_compute_drift_compliant_returns_empty():
    facts = DeviceFacts(device="nyc-acc-01", model="cEOSLab", version="4.33.1F")
    assert compute_drift(INTENT, facts, []) == []
