from netops_temporal.tools import check_lab
from netops_temporal.tools.check_lab import CheckResult


def test_failed_device_check_prints_hint(monkeypatch, capsys):
    monkeypatch.setattr(
        check_lab,
        "run_checks",
        lambda: [
            CheckResult("temporal", True, "localhost:7233"),
            CheckResult("bos-rtr-01 eAPI", False, "timed out"),
        ],
    )
    assert check_lab.main() == 1
    out = capsys.readouterr().out
    assert "bos-rtr-01 eAPI" in out
    assert "docs/lab-setup.md#macos-networking" in out


def test_all_green_returns_zero(monkeypatch, capsys):
    monkeypatch.setattr(check_lab, "run_checks", lambda: [CheckResult("temporal", True, "ok")])
    assert check_lab.main() == 0
    assert "macos-networking" not in capsys.readouterr().out


def test_mock_mode_skips_devices(monkeypatch):
    monkeypatch.setenv("LAB_MODE", "mock")
    monkeypatch.setattr(check_lab, "check_temporal", lambda: CheckResult("temporal", True, "ok"))
    results = check_lab.run_checks()
    others = [r for r in results if r.name != "temporal"]
    assert len(others) == 9  # eAPI + SSH for 4 devices, plus Nautobot
    assert all(r.ok and r.detail == "mock mode" for r in others)
