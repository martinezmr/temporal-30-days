"""Day 14: the mock lab remembers pushed config lines, in a file, across worker restarts."""

from concurrent.futures import ThreadPoolExecutor

from netops_temporal.mock import devices, state


def test_applied_lines_show_up_in_running_config():
    assert "ntp server 192.0.2.10" not in devices.running_config("bos-acc-01")
    state.apply_lines("bos-acc-01", ["ntp server 192.0.2.10"])
    assert state.applied_lines("bos-acc-01") == ["ntp server 192.0.2.10"]
    assert "ntp server 192.0.2.10" in devices.running_config("bos-acc-01").splitlines()


def test_rollback_removes_the_last_push_only():
    state.apply_lines("bos-rtr-01", ["ntp server 192.0.2.10"])
    state.apply_lines("bos-rtr-01", ["logging host 192.0.2.50"])
    state.rollback("bos-rtr-01")
    assert state.applied_lines("bos-rtr-01") == ["ntp server 192.0.2.10"]


def test_state_is_a_file_under_output_dir(mock_lab):
    state.apply_lines("nyc-rtr-01", ["ntp server 192.0.2.10"])
    assert (mock_lab / "mock-state.json").exists()
    state.reset()
    assert state.applied_lines("nyc-rtr-01") == []


def test_concurrent_pushes_to_different_devices_all_stick():
    """Activities run in a thread pool, so two remediations can push at the same moment."""
    devices_ = ["bos-acc-01", "bos-rtr-01", "nyc-acc-01", "nyc-rtr-01"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i in range(25):
            for d in devices_:
                pool.submit(state.apply_lines, d, [f"line {i}"])
    for d in devices_:
        assert len(state.applied_lines(d)) == 25


def test_pushed_lines_are_their_own_lines_on_every_device():
    # Some fixture configs don't end with a newline; a push must still be its own line.
    for device in ["bos-acc-01", "bos-rtr-01", "nyc-acc-01", "nyc-rtr-01"]:
        state.apply_lines(device, ["ntp server 192.0.2.10"])
        assert "ntp server 192.0.2.10" in devices.running_config(device).splitlines()
