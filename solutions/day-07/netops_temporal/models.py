"""Inputs and outputs that cross workflow/activity boundaries. Day 3 onward: no bare dicts."""

from datetime import datetime

from pydantic import BaseModel, Field

from netops_temporal.constants import DEVICES


class FactsRequest(BaseModel):
    """Input to GetFactsWorkflow and get_device_facts.

    One model instead of positional arguments, so a field can be added later without
    breaking workflows that are already running.
    """

    device: str


class DeviceFacts(BaseModel):
    device: str
    model: str
    version: str


class FactsReport(BaseModel):
    facts: DeviceFacts
    collected_at: datetime


class ShowTechRequest(BaseModel):
    device: str


class ShowTechResult(BaseModel):
    """Where the outputs were written. The outputs themselves stay out of workflow history."""

    device: str
    output_dir: str
    commands_collected: int
    resumed_from: int


class DeviceIntent(BaseModel):
    """What Nautobot says a device should be."""

    device: str
    role: str
    location: str
    target_version: str


class BackupRequest(BaseModel):
    devices: list[str] = Field(default_factory=lambda: list(DEVICES))


class BackupConfigRequest(BaseModel):
    device: str
    timestamp: str


class IntentRequest(BaseModel):
    device: str


class DeviceBackupResult(BaseModel):
    device: str
    ok: bool
    backup_path: str | None = None
    intent: DeviceIntent | None = None
    error: str | None = None


class BackupReport(BaseModel):
    started_at: datetime
    results: list[DeviceBackupResult]

    @property
    def succeeded(self) -> list[str]:
        return [r.device for r in self.results if r.ok]

    @property
    def failed(self) -> list[str]:
        return [r.device for r in self.results if not r.ok]
