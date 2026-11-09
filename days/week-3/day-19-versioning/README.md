# Day 19 — Changing a workflow while it's running: patching

[← Day 18](../day-18-schedules/README.md) · [Day 20 →](../day-20-observability/README.md)

**Time:** 90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-19/`](../../../solutions/day-19/)

## Why today matters

The auditors have a new request: every nightly audit must keep a copy of each device's config,
as evidence of what was audited. Easy change: back up every device before checking it. You
deploy it at 02:03, three minutes into tonight's audit, and the audit gets stuck. Nothing fails,
nothing finishes, and the worker log says `Nondeterminism error`.

Day 4 explained why: a worker that picks up a workflow replays its history, and the code must
make the same commands in the same order. Code that's changed can't do that for runs that
started before the change. Today you make the change the safe way, with `workflow.patched()`,
and you see the stuck audit for yourself first.

## Concept

### What breaks, exactly

The Day 18 audit's history starts with `fetch_device_intent` and `get_device_facts` being
scheduled. The new code's first command is `backup_running_config`. A worker replaying the old
history with the new code sees:

```
[TMPRL1100] Nondeterminism error: Activity type of scheduled event 'fetch_device_intent'
does not match activity type of activity command 'backup_running_config'
```

The worker fails the workflow task and tries again, and again. The workflow stays **Running**
and stuck until a worker with compatible code picks it up. (That's on purpose: Temporal never
guesses. Your code gets fixed and the workflow carries on.)

Only **in-flight** runs are affected. New runs start on the new code without trouble.

### `workflow.patched()` branches on history

```python
if workflow.patched("audit-backup-evidence"):
    ...  # the new code
```

- **A new run** (no history yet): `patched` returns `True` and writes a **marker** into history.
  The new code runs.
- **Replaying a run that has the marker** (started on the new code): `True`. The new code runs,
  same as the first time.
- **Replaying a run without the marker** (started before the change): `False`. The old path runs,
  and its commands match the history.

So the one workflow type runs old and new code side by side, decided per run by its own history.

### The patch lifecycle

A patch isn't forever. Three steps, each a deploy:

| Step | Code | Safe when |
| --- | --- | --- |
| 1. Patch | `if workflow.patched(ID): new else: old` | Always |
| 2. Deprecate | `workflow.deprecate_patch(ID)`, then only the new code | No running workflow started before step 1 |
| 3. Remove | Only the new code, no patch call | No running workflow started before step 2 |

`deprecate_patch` still writes the marker, so runs started on step 1 or 2 code agree with step 3
code. Each step waits until the runs from before it have finished. For a nightly audit that's a
day; for a long-running orchestrator it can be "until it next continues as new". Leftover
replay test histories from before a step have to go when you take it.

Day 30 shows the other approach, **worker versioning**: old runs stay on old workers, so the code
doesn't need branches. Patching is for when you can't (or don't want to) run two worker builds.

### Which changes need a patch?

Anything that changes the **commands** a workflow makes, or their order: adding, removing or
reordering activities, timers or child workflows, or changing an activity's type. Changing what
happens *inside* an activity doesn't, and neither does moving workflow code around while keeping
the commands the same (Day 18's `compliance_cycle.py`). If in doubt, the replay test tells you.

## Walkthrough

### 1. Save a history from before the change

Before touching the code, run one Day 18 audit and save its history:

```bash
temporal workflow execute --type ComplianceAuditWorkflow --task-queue netops-orchestration \
  --workflow-id audit-v1-example --input '{}'
uv run --env-file .env python -m netops_temporal.tools.export_history audit-v1-example \
  tests/histories/audit_v1.json
```

This file is the proof, from now on, that old audits still replay. (Day 6's replay test picks it
up automatically.)

### 2. `workflows/audit.py`: the patch

```python
# file: netops_temporal/workflows/audit.py
# Day 19. The patch ID is permanent once deployed: it's written into every new audit's history.
BACKUP_EVIDENCE = "audit-backup-evidence"
```

```python
# file: netops_temporal/workflows/audit.py
        started_at = workflow.now()
        backups: dict[str, str] = {}
        # New audits: True, and a marker goes into history. Replaying an audit that started
        # before this code existed: False (no marker in its history), so it skips the new step
        # and replays exactly the commands it recorded.
        if workflow.patched(BACKUP_EVIDENCE):
            backups = await backup_evidence(req.devices, started_at)
        # The same check the orchestrator runs each cycle. It only reports: no remediation.
        states = await collect_compliance(req.devices)
```

`backup_evidence` runs Day 7's `backup_running_config` for every device in parallel. A device
whose backup fails gets `"backup failed: ..."` instead of a path; the check right after reports
it as `unknown` anyway.

### 3. `models.py`

```python
# file: netops_temporal/models.py
    # Day 19: device -> backup file, kept as audit evidence. Empty for audits from before.
    backups: dict[str, str] = Field(default_factory=dict)
```

A new field with a default: results from old audits (without it) still load.

### 4. `tests/test_patching.py`

- `test_v1_history_replays_with_patch`: the saved v1 history replays against today's code.
- `test_v1_history_fails_without_patch`: a copy of the workflow in the test file, with the new
  step and no `patched()` guard, raises `NondeterminismError` on the same history. That's the
  stuck audit, as a test.
- `test_new_runs_take_patched_path`: a new audit has a **MarkerRecorded** event, then
  `backup_running_config` as its first activity, and a backup file per device.

## Run it

Restart the worker on the new code and trigger the schedule (or start an audit by hand):

```bash
uv run --env-file .env python -m netops_temporal.tools.schedules create
uv run --env-file .env python -m netops_temporal.tools.schedules trigger
```

Open the audit in the UI. Event 5 is **MarkerRecorded** (click it: the patch ID is in its
details), then four `backup_running_config` activities, then the checks. The result has a
`backups` map, and the files are under `output/backups/`.

## Break it

1. **Deploy without the patch.** This is the 02:03 deploy. Use `LAB_MODE=mock MOCK_CLI_DELAY=8`
   so the audit is slow.
   1. Run the worker with **Day 18's** code (`scripts/solution.sh 18 python -m netops_temporal.workers.main`)
      and start an audit:
      `temporal workflow start --type ComplianceAuditWorkflow --task-queue netops-orchestration --workflow-id audit-live --input '{}'`.
   2. Within a few seconds, stop the worker (Ctrl-C).
   3. In your Day 19 code, replace `if workflow.patched(BACKUP_EVIDENCE):` with `if True:`, and
      start the worker on it.
   4. Wait. The in-flight activities belonged to the dead worker, so nothing happens until they
      time out (60 s) and are retried. Then the worker log shows the `TMPRL1100 Nondeterminism
      error`, and in the UI `audit-live` is **Running** with a failed workflow task.
   5. Put the `patched()` line back and restart the worker. `audit-live` finishes, with
      `backups: {}`: it took the old path, because its history has no marker. Start another
      audit: it has the marker and the backups.
2. **Remove the patch too early.** Replace the `if workflow.patched(...)` block with
   `workflow.deprecate_patch(BACKUP_EVIDENCE)` and an unconditional
   `backups = await backup_evidence(...)`. Run `scripts/test-solutions.sh 19`:
   `test_replay_committed_histories[audit_v1]` and `test_v1_history_replays_with_patch` fail.
   That's step 2 of the lifecycle taken while a v1 audit could still be running. Put it back.

## Check yourself

1. Why does a code change break a workflow that's already running, but not new ones?
2. What does `workflow.patched("x")` return for a new run, a run started on the new code, and a
   run started before?
3. What are the three steps of the patch lifecycle, and when is each one safe?
4. Which of these needs a patch: adding an activity; changing an activity's retry count; changing
   how an activity parses `show version`; reordering two activities?
5. Why was the replay history saved *before* the change?

<details>
<summary>Answers</summary>

1. A running workflow is replayed from its history on whatever worker picks it up, and the new
   code makes different commands than the history recorded. A new run has no history to
   disagree with.
2. `True` (and writes a marker); `True` (the marker is in its history); `False` (no marker).
3. Patch (`if patched: new else: old`), always safe. Deprecate (`deprecate_patch`, new code only),
   once no runs from before the patch are running. Remove (no patch call), once no runs from
   before the deprecation are running.
4. Adding an activity and reordering activities change the commands: patch. Activity options like
   retries aren't part of the command match in replay, and parsing happens inside the activity:
   neither needs a patch. (When unsure, run the replay test.)
5. It's the proof that old runs replay. A history recorded after the change would only show that
   new runs replay with new code, which they always do.

</details>

## Solution

[`solutions/day-19/`](../../../solutions/day-19/): the patched backup-evidence step in
`workflows/audit.py`, `AuditReport.backups` in `models.py`, and
`tests/histories/audit_v1.json` (a Day 18 audit). `tests/test_patching.py` checks that the old
history replays with the patch, fails without it, and that new audits take the new path.
