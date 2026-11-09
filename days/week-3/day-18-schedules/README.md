# Day 18 — Schedules: a nightly audit you can pause and replay

[← Day 17](../day-17-saga-rollback/README.md) · [Day 19 →](../day-19-versioning/README.md)

**Time:** 60 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-18/`](../../../solutions/day-18/)

## Why today matters

Every network team has a cron job somewhere: a nightly config audit on a box under someone's
desk. Nobody knows it stopped running until the auditors ask for last month's reports. Pausing it
for a change freeze means commenting out a crontab line and remembering to put it back. And when
the box was down for three nights, there's no "run the ones I missed".

Today you replace that cron job with a **Temporal Schedule**: a nightly compliance audit that's
visible in the UI, shows its next run time, can be paused with a note saying why, triggered on
demand, and **backfilled** for the nights it missed.

## Concept

### Three ways to run something regularly

| | Cron job | A loop with timers (the orchestrator) | Temporal Schedule |
| --- | --- | --- | --- |
| Shape | A script, started by the OS | One long-running workflow | A new workflow per run |
| State between runs | None (or a file) | Yes: in the workflow | None: each run stands alone |
| See the next run, pause, trigger | No | Signals you write yourself | Built in, in the UI and CLI |
| Missed runs (worker down) | Lost | Delayed: the timer fires late | Caught up, or backfilled on demand |

Rule of thumb: if the job needs **memory** from one run to the next (the orchestrator's state, its
cycle count, its interval), it's a workflow with timers. If every run **stands alone** (a full
audit, a report), it's a schedule.

### Overlap policy

What if it's 02:00 and last night's audit is somehow still running?

| `ScheduleOverlapPolicy` | Meaning |
| --- | --- |
| `SKIP` (the default) | Don't start a new one; count it as skipped |
| `BUFFER_ONE` | Start it when the current one finishes (one waits at most) |
| `BUFFER_ALL` | Queue every one and run them in order |
| `CANCEL_OTHER` / `TERMINATE_OTHER` | Stop the running one, start the new one |
| `ALLOW_ALL` | Run them side by side |

An audit is pointless twice at once, so the nightly audit uses `SKIP`.

### Backfill

A backfill says "start the runs that would have happened between these two times". It's for after
an outage, or when you add a schedule and want history to start from last week. Each missed run
gets the ID it would have had (`audit-2026-11-03T02:00:00Z`), and the overlap policy applies:
with `SKIP`, six missed nights all "due" at once start just **one** audit (the other five overlap
it). With `ALLOW_ALL`, all six start at once.

### Pause with a note

A paused schedule starts nothing until it's unpaused, and the pause carries a note: "change
freeze CHG-1234". The note is right there in the UI, so the next person knows why it's off and
who to ask.

### A shared cycle

The audit checks the same things as one orchestrator cycle. Rather than copy the code, the cycle
moves into `workflows/compliance_cycle.py`, and both workflows call it. A plain `async` function
called from workflow code runs **inside** that workflow: its activities appear in the caller's
history, and the same determinism rules apply to it.

## Walkthrough

### 1. `models.py`

```python
# file: netops_temporal/models.py
class AuditRequest(BaseModel):
    """Day 18: what the nightly audit checks."""

    devices: list[str] = Field(default_factory=lambda: list(DEVICES))


class AuditReport(BaseModel):
    started_at: datetime
    states: dict[str, ComplianceState]
```

### 2. `workflows/compliance_cycle.py`: the cycle, out of the orchestrator

```python
# file: netops_temporal/workflows/compliance_cycle.py
async def collect_compliance(devices: list[str]) -> dict[str, ComplianceState]:
    """Check every device in parallel (Day 7's fan-out)."""
    results = await asyncio.gather(*(check_device(d) for d in devices))
    return {s.device: s for s in results}
```

`check_device` is Day 14's method, moved here unchanged as a plain function. The orchestrator's
loop now starts with:

```python
# file: netops_temporal/workflows/orchestrator.py
            results = list((await collect_compliance(inp.devices)).values())
```

Moving code like this doesn't change the commands it produces (same activities, same order), so
running orchestrators replay fine. Day 19 is about changes that *do*.

### 3. `workflows/audit.py`: one run, one report

```python
# file: netops_temporal/workflows/audit.py
@workflow.defn
class ComplianceAuditWorkflow:
    @workflow.run
    async def run(self, req: AuditRequest) -> AuditReport:
        started_at = workflow.now()
        # The same check the orchestrator runs each cycle. It only reports: no remediation.
        states = await collect_compliance(req.devices)
```

It returns the report and finishes. No loop, no signals, no remediation.

### 4. `tools/schedules.py`: the schedule

```python
# file: netops_temporal/tools/schedules.py
def nightly_audit_schedule(
    hour_utc: int = 2, task_queue: str = ORCHESTRATION_TASK_QUEUE
) -> Schedule:
    """Every night at `hour_utc`:00 UTC, start a ComplianceAuditWorkflow."""
    return Schedule(
        action=ScheduleActionStartWorkflow(
            ComplianceAuditWorkflow.run,
            AuditRequest(),
            # The schedule appends the scheduled time, so each run gets its own ID:
            # audit-2026-11-09T02:00:00Z.
            id="audit",
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(cron_expressions=[f"0 {hour_utc} * * *"]),
        # If last night's audit is somehow still running, don't start another on top of it.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
```

A pure function that builds the `Schedule`, so a unit test can check it without a server. The
cron is in UTC. (`ScheduleSpec(time_zone_name="America/Chicago")` makes it local time, daylight
saving included.) The rest of the file is a small CLI: `create`, `trigger`, `pause <note>`,
`unpause`, `backfill <days> [allow-all]` and `delete`.

### 5. Tests

- `test_audit_report_matches_orchestrator_cycle`: an audit and one orchestrator cycle find the
  same thing on every device.
- `test_schedule_builder_cron_and_overlap`: the builder alone.
- `test_schedule_trigger_starts_audit`: on a real dev server (`dev_env`, Day 15), because the
  time-skipping test server doesn't run schedules. It creates the schedule, triggers it, and
  waits for the audit's report.

## Run it

Restart the worker (`ComplianceAuditWorkflow` is registered). Then:

```bash
uv run --env-file .env python -m netops_temporal.tools.schedules create
uv run --env-file .env python -m netops_temporal.tools.schedules trigger
```

In the UI, open **Schedules** → `nightly-audit`: the cron, the next run (`02:00 UTC` tomorrow) and
a recent run. Click the run: a `ComplianceAuditWorkflow` with an ID like
`audit-2026-11-08T17:20:40Z`, and its result is the report. The CLI shows the same:

```bash
temporal schedule describe --schedule-id nightly-audit
temporal workflow list --query 'WorkflowType="ComplianceAuditWorkflow"'
```

## Break it

Start the worker with `LAB_MODE=mock MOCK_CLI_DELAY=3`, so each audit takes a few seconds.

1. **Trigger twice, fast.** Run `trigger` twice in a row. One audit runs, and
   `temporal schedule describe --schedule-id nightly-audit` shows
   `ActionCounts {"Total":1,"MissedCatchupWindow":0,"SkippedOverlap":1}`. That's `SKIP`.
2. **Backfill a week.** `... schedules backfill 6`: just one audit starts (the other five
   overlapped it). Then `... schedules backfill 6 allow-all`: six audits start at once, one per
   missed night, each with that night's ID. (An audit ID can be used again once the earlier
   run with that ID has finished: Day 16's reuse policy.)
3. **Pause for a change freeze.** `... schedules pause "change freeze CHG-1234"`. In the UI the
   schedule shows **Paused** with your note. `trigger` still works while paused (it's a manual
   run); the 02:00 run won't happen. `unpause` when the freeze is over.

`delete` when you're done.

## Check yourself

1. Why is the orchestrator a loop with timers, but the audit a schedule?
2. What does `SKIP` do when a run is due and the previous one is still running?
3. The worker was down for three nights. What does a backfill do, and how does `SKIP` affect it?
4. Why did the compliance cycle move into its own module, and does that break running
   orchestrators?
5. Why does the schedule test use the real dev server?

<details>
<summary>Answers</summary>

1. The orchestrator keeps state from cycle to cycle (results, cycle count, interval), so it's one
   workflow that waits. Each audit stands alone, so a schedule starting a fresh workflow per night
   is simpler, and it comes with pause, trigger and backfill.
2. It doesn't start the new run, and counts it as skipped.
3. It starts the runs that should have happened in that window. They're all due at once, so with
   `SKIP` only the first one runs; with `ALLOW_ALL` (or `BUFFER_ALL`, one after another) they
   all do.
4. So the audit and the orchestrator run exactly the same check, from one piece of code. It's not
   a breaking change: the same activities are scheduled in the same order, so history replays.
5. The time-skipping test server doesn't implement schedules.

</details>

## Solution

[`solutions/day-18/`](../../../solutions/day-18/): new `workflows/compliance_cycle.py` (the
cycle, moved out of the orchestrator), `workflows/audit.py` and `tools/schedules.py`;
`AuditRequest` and `AuditReport` in `models.py`. `tests/test_audit.py` checks the audit matches an
orchestrator cycle and starts no remediation; `tests/test_schedules.py` checks the builder and a
triggered run on a real dev server.
