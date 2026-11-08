"""Day 7: back up every device in parallel, fetch intent, and report partial failures."""

import uuid
from pathlib import Path
from types import SimpleNamespace

import pyeapi.eapilib
import pytest
from temporalio.api.enums.v1 import EventType

from netops_temporal.devices import napalm_eos
from netops_temporal.devices.errors import (
    DeviceAuthError,
    DeviceUnreachableError,
    UnknownDeviceError,
)
from netops_temporal.models import BackupReport, BackupRequest
from netops_temporal.sot import nautobot
from netops_temporal.workflows.backup import ConfigBackupWorkflow


async def run_backup(env, worker, **request):
    handle = await env.client.start_workflow(
        ConfigBackupWorkflow.run,
        BackupRequest(**request),
        id=str(uuid.uuid4()),
        task_queue=worker.task_queue,
    )
    return await handle.result(), await handle.fetch_history()


async def test_backup_all_devices_mock(workflow_env, worker):
    report, _ = await run_backup(workflow_env, worker)

    assert isinstance(report, BackupReport)
    assert report.succeeded == ["bos-rtr-01", "bos-acc-01", "nyc-rtr-01", "nyc-acc-01"]
    assert report.failed == []
    for result in report.results:
        assert "hostname " + result.device in Path(result.backup_path).read_text()
    by_device = {r.device: r for r in report.results}
    assert by_device["nyc-acc-01"].intent.target_version == "4.33.1F"
    assert by_device["bos-rtr-01"].intent.role == "router"


async def test_partial_failure_reported_not_raised(workflow_env, worker, monkeypatch):
    monkeypatch.setenv("MOCK_UNREACHABLE", "nyc-rtr-01")
    report, _ = await run_backup(workflow_env, worker)

    assert report.failed == ["nyc-rtr-01"]
    assert len(report.succeeded) == 3
    [failed] = [r for r in report.results if not r.ok]
    assert "unreachable" in failed.error


async def test_backups_run_in_parallel(workflow_env, worker):
    _, history = await run_backup(workflow_env, worker)

    events = list(history.events)
    scheduled = [
        i for i, e in enumerate(events)
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
        and e.activity_task_scheduled_event_attributes.activity_type.name
        == "backup_running_config"
    ]
    first_completed = next(
        i for i, e in enumerate(events)
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED
    )
    assert len(scheduled) == 4
    assert max(scheduled) < first_completed


async def test_timestamp_is_deterministic(workflow_env, worker):
    before = await workflow_env.get_current_time()
    report, _ = await run_backup(workflow_env, worker, devices=["bos-rtr-01"])

    assert abs((report.started_at - before).total_seconds()) < 1
    [result] = report.results
    assert Path(result.backup_path).name == f"{report.started_at:%Y%m%dT%H%M%SZ}.cfg"


def test_nautobot_device_not_found(monkeypatch):
    monkeypatch.setenv("LAB_MODE", "live")
    fake_api = SimpleNamespace(dcim=SimpleNamespace(devices=SimpleNamespace(get=lambda **_: None)))
    monkeypatch.setattr(nautobot.pynautobot, "api", lambda *a, **kw: fake_api)
    with pytest.raises(UnknownDeviceError, match="bos-rtr-01"):
        nautobot.get_device_intent("bos-rtr-01")


class LazyEosDriver:
    """Like NAPALM's EOS driver: open() succeeds, the first real call hits the device."""

    def __init__(self, message: str):
        self.message = message

    def open(self):
        pass

    def get_config(self, retrieve):
        raise pyeapi.eapilib.ConnectionError("https://127.0.0.1:8441", self.message)

    def close(self):
        pass


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Unauthorized. Unable to authenticate user: Bad username/password combination",
         DeviceAuthError),
        ("Socket error during eAPI connection: [Errno 61] Connection refused",
         DeviceUnreachableError),
    ],
)
def test_napalm_maps_errors_from_lazy_connection(monkeypatch, message, expected):
    monkeypatch.setenv("LAB_MODE", "live")
    monkeypatch.setattr(
        napalm_eos, "get_network_driver", lambda name: lambda **kw: LazyEosDriver(message)
    )
    with pytest.raises(expected):
        napalm_eos.get_running_config("bos-rtr-01")
