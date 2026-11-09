"""Day 14: compare intent with what a device reports. Pure and deterministic, so the
orchestrator can call it directly inside the workflow: no activity needed."""

from netops_temporal.models import DeviceFacts, DeviceIntent, DriftReport


def compute_drift(
    intent: DeviceIntent, facts: DeviceFacts, missing_lines: list[str]
) -> list[DriftReport]:
    drift = []
    if facts.version != intent.target_version:
        drift.append(
            DriftReport(
                device=intent.device,
                kind="version",
                expected=intent.target_version,
                actual=facts.version,
            )
        )
    if missing_lines:
        drift.append(
            DriftReport(
                device=intent.device,
                kind="config",
                expected=f"{len(missing_lines)} policy line(s) present",
                actual=f"{len(missing_lines)} missing",
                missing_lines=missing_lines,
            )
        )
    return drift
