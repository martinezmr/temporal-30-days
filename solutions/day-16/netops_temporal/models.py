"""Inputs and outputs that cross workflow/activity boundaries. Day 3 onward: no bare dicts."""

from datetime import datetime
from typing import Literal

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


class WatchRequest(BaseModel):
    """Input to DeviceWatchWorkflow: which device, and how often to check it."""

    device: str
    interval_seconds: int = 300
    # Day 12: state carried from one run to the next by continue-as-new. A fresh watch
    # starts with the defaults.
    checks_so_far: int = 0
    last_facts: DeviceFacts | None = None
    last_error: str | None = None
    paused: bool = False
    max_checks_per_run: int = 500


class WatchStatus(BaseModel):
    """What DeviceWatchWorkflow.status returns: a snapshot of the workflow's state."""

    device: str
    paused: bool
    checks: int
    last_facts: DeviceFacts | None
    last_error: str | None
    interval_seconds: int = 300


class SetIntervalRequest(BaseModel):
    """Input to the DeviceWatchWorkflow.set_interval update."""

    interval_seconds: int


class MaintenanceWindow(BaseModel):
    """A daily window, in UTC, when changes are allowed. It may cross midnight."""

    start_hour_utc: int = Field(ge=0, le=23)
    duration_hours: int = Field(ge=1, le=24)


class ChangeWindowRequest(BaseModel):
    device: str
    window: MaintenanceWindow
    approval_timeout_minutes: int = Field(default=60, ge=1)


class ChangeWindowResult(BaseModel):
    device: str
    approved: bool
    reason: str
    ran_at: datetime | None = None
    backup_path: str | None = None


class OperationRequest(BaseModel):
    """One thing someone wants done on a device, submitted to its DeviceEntityWorkflow."""

    kind: Literal["facts", "backup"]
    requested_by: str


class OperationResult(BaseModel):
    kind: Literal["facts", "backup"]
    requested_by: str
    ok: bool
    detail: str


class DeviceEntityInput(BaseModel):
    device: str
    max_ops_per_run: int = 200
    # Handed over by continue-as-new, so the `recent` query survives roll-overs.
    recent: list[OperationResult] = Field(default_factory=list)


class DriftReport(BaseModel):
    """One way a device differs from its intent."""

    device: str
    kind: Literal["version", "config"]
    expected: str
    actual: str
    missing_lines: list[str] = Field(default_factory=list)


class ComplianceCheckRequest(BaseModel):
    device: str
    required_lines: list[str]


class ComplianceState(BaseModel):
    """What the orchestrator knows about one device after its latest check."""

    device: str
    status: Literal["compliant", "drifted", "unknown"]
    drift: list[DriftReport] = Field(default_factory=list)
    checked_at: datetime
    error: str | None = None
    # Day 15: what the last remediation child did about it.
    remediation: str | None = None


class OrchestratorInput(BaseModel):
    devices: list[str] = Field(default_factory=lambda: list(DEVICES))
    interval_seconds: int = 900
    max_cycles_per_run: int = 50
    # Day 15: remediation children only plan (dry run) unless this is turned off (Day 17).
    dry_run: bool = True
    # Day 16: never remediate more than this many devices at once.
    max_parallel_remediations: int = 2
    # Handed over by continue-as-new.
    state: dict[str, ComplianceState] = Field(default_factory=dict)
    cycles: int = 0


class RemediationRequest(BaseModel):
    device: str
    missing_lines: list[str]
    dry_run: bool = True


class RemediationResult(BaseModel):
    device: str
    ok: bool
    pushed_lines: list[str] = Field(default_factory=list)
    diff: str = ""
    rolled_back: bool = False
    error: str | None = None


class UpgradeRequest(BaseModel):
    device: str
    target_version: str


class UpgradeResult(BaseModel):
    device: str
    ok: bool
    detail: str
