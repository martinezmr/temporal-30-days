# Day 29 — Assemble NetworkComplianceOrchestrator

[← Week 4](../../week-4/README.md) · [Day 30 →](../day-30-ocp-cicd/README.md)

## Goal

Everything from the month, working together, end to end.

## Architecture

```
              Operators · nightly schedule · AI approvals
                         │ signals / queries / updates
┌──────────── namespace: default ─────────────┐     ┌──── namespace: compliance ────┐
│  NetworkComplianceOrchestrator (entity)     │────▶│  compliance-endpoint (Nexus)  │
│    ├─ DeviceUpgradeWorkflow (child)         │     │    └─ ConfigComplianceWorkflow │
│    └─ Troubleshooting agent (child)         │     │        (saga + rollback)       │
└──────┬───────────────┬──────────────┬───────┘     └──────────────┬────────────────┘
       │ intent        │ model calls  │ state                      │ config changes
   Nautobot         LLM API         4 × Arista cEOS ◀──────────────┘
```

The orchestrator only decides. Every device change happens in a child workflow or behind the Nexus endpoint, and every external call is an activity.

## One drift cycle

1. The 15-minute timer fires (or `force_check`, or the nightly schedule's audit).
2. Activities on `netops-device-io` fetch intent from Nautobot and state from all 4 devices in parallel.
3. `compute_drift` returns `DriftReport`s; the orchestrator upserts `ComplianceState` per device.
4. For each drifted device, `explain_drift` attaches a summary and risk level.
5. **Config drift** → Nexus `remediate` → `ConfigComplianceWorkflow` in `compliance` (through the Day 27 approval gate when risk is medium/high).
6. **Version drift** → `DeviceUpgradeWorkflow` child (`ABANDON`), waiting for the device's maintenance window.
7. Children report back; the orchestrator updates state and continues-as-new on schedule.

## DeviceUpgradeWorkflow in the lab

cEOS can't be upgraded in place, so its activities are stand-ins with the real shape:
pre-checks (BGP/LLDP snapshot) → image present? → wait for window → "reload" (a timer) → wait for reachability → post-checks diffed against pre-checks → rollback path if they differ.

## Final test

- [ ] Change an interface description on `bos-acc-01` by hand → config path runs, low risk, auto-remediated.
- [ ] Add a non-compliant ACL on `nyc-acc-01` → high risk, waits for your approval, you approve, it's fixed.
- [ ] Bump `nyc-rtr-01`'s target version in Nautobot → upgrade path waits for the window (use `emergency_override` to skip).
- [ ] Restart every container mid-run. Everything finishes.
