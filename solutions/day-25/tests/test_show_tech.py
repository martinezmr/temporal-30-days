"""Day 5: a long Netmiko activity that heartbeats, resumes, and can be cancelled."""

import dataclasses

import pytest
from temporalio.exceptions import CancelledError
from temporalio.testing import ActivityEnvironment

from netops_temporal.activities.show_tech import collect_show_tech
from netops_temporal.constants import SHOW_TECH_COMMANDS
from netops_temporal.mock import devices as mock_devices
from netops_temporal.models import ShowTechRequest, ShowTechResult


@pytest.fixture
def cli_calls(monkeypatch):
    calls = []
    real_cli = mock_devices.cli

    def counting_cli(device, command):
        calls.append(command)
        return real_cli(device, command)

    monkeypatch.setattr(mock_devices, "cli", counting_cli)
    return calls


def output_files(tmp_path):
    return sorted(p.name for p in (tmp_path / "show-tech" / "bos-rtr-01").glob("*.txt"))


def test_collects_all_ten_and_heartbeats(tmp_path):
    env = ActivityEnvironment()
    heartbeats = []
    env.on_heartbeat = lambda *details: heartbeats.append(details[0])

    result = env.run(collect_show_tech, ShowTechRequest(device="bos-rtr-01"))

    assert result.commands_collected == 10
    assert result.resumed_from == 0
    assert heartbeats == list(range(1, 11))
    assert output_files(tmp_path) == [f"{n:02d}.txt" for n in range(1, 11)]


def test_resumes_from_heartbeat_details(cli_calls):
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, heartbeat_details=[4])

    result = env.run(collect_show_tech, ShowTechRequest(device="bos-rtr-01"))

    assert result.resumed_from == 4
    assert result.commands_collected == 10
    assert cli_calls == SHOW_TECH_COMMANDS[4:]


def test_result_contains_no_command_output():
    result = ActivityEnvironment().run(collect_show_tech, ShowTechRequest(device="bos-rtr-01"))
    assert isinstance(result, ShowTechResult)
    assert len(result.model_dump_json()) < 1024


def test_cancellation_stops_early(tmp_path):
    env = ActivityEnvironment()

    def on_heartbeat(*details):
        if details[0] == 3:
            env.cancel()

    env.on_heartbeat = on_heartbeat
    with pytest.raises(CancelledError):
        env.run(collect_show_tech, ShowTechRequest(device="bos-rtr-01"))
    assert 3 <= len(output_files(tmp_path)) < 10
