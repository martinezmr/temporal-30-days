# Day 18 — Schedules

[← Day 17](../day-17-saga-rollback/README.md) · [Day 19 →](../day-19-versioning/README.md)

## Goal

A nightly full audit that you can pause, trigger and backfill from the UI.

## Learn

- Schedules replace cron: visible in the UI, pausable, with overlap policies and backfill.
- Stateful loop (the orchestrator) → a timer. Stateless periodic job (full audit) → a schedule.
- Docs: [Schedules](https://docs.temporal.io/develop/python/workflows/schedules)

## Build

`FullComplianceAuditWorkflow` — every device, every check, writes a report. Then:

```python
await client.create_schedule(
    "nightly-compliance-audit",
    Schedule(
        action=ScheduleActionStartWorkflow(
            FullComplianceAuditWorkflow.run, id="full-audit", task_queue=ORCHESTRATION_TASK_QUEUE),
        spec=ScheduleSpec(cron_expressions=["0 6 * * *"]),   # 01:00 Central = 06:00 UTC (CDT shifts it)
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    ),
)
```

Or set `time_zone_name="America/Chicago"` on the spec to stop doing UTC math.

## CLI

```bash
temporal schedule list
temporal schedule trigger --schedule-id nightly-compliance-audit
temporal schedule toggle  --schedule-id nightly-compliance-audit --pause --reason "change freeze"
temporal schedule backfill --schedule-id nightly-compliance-audit \
  --start-time 2026-10-01T00:00:00Z --end-time 2026-10-03T00:00:00Z
```

## Done when

- [ ] The schedule shows in the UI with its next run time, and a manual trigger works.
