# Day 17 — Saga: a config push that undoes itself

[← Day 16](../day-16-fan-out/README.md) · [Day 18 →](../day-18-schedules/README.md)

**Time:** 90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works; the live lab gets real config pushes) · **Solution:** [`solutions/day-17/`](../../../solutions/day-17/)

## Why today matters

Until now the orchestrator only *planned* fixes. Today it pushes config to devices for real, and
that's where automation earns its reputation, good or bad. The script that pushes NTP to 400
switches is fine until switch 212 times out halfway, or the push "succeeds" and the line isn't
there, or someone hits Ctrl-C. Then you have a fleet in an unknown state and a long night.

The fix is an old idea from databases called a **saga**: every step that changes something
registers how to undo it, and if a later step fails, the undos run in reverse. Temporal makes the
saga reliable, because the list of what was done is in history. A worker crash in the middle
doesn't forget that the push happened.

## Concept

### A saga is a list of undos

```
backup  ->  push  ->  verify
              |
              +-- registers: rollback
```

- Each step that **changes the device** adds its undo to a list, *after* it succeeds.
- If a later step fails, run the list backwards.
- If the step that failed is the first change, the list is empty: nothing to undo.

Steps that don't change anything (backup, verify) have no undo.

Network analogy: a change plan with a backout section, where each line of the backout was
written down the moment its step was done.

### NAPALM gives you the undo

NAPALM's EOS driver uses an EOS config session:

| NAPALM call | What EOS does |
| --- | --- |
| `load_merge_candidate(config=...)` | Stages the lines in a config session. Nothing changes yet. |
| `compare_config()` | The real diff between the session and the running config. |
| `commit_config()` | Saves the startup config to `flash:rollback-0`, commits the session, then `write memory`. |
| `discard_config()` | Throws the session away. |
| `rollback()` | `configure replace flash:rollback-0`: back to how it was before the last commit. |

`rollback()` works from a new connection, because the "before" copy lives on the device's flash.
That matters: the undo runs in a different activity, maybe on a different worker, maybe hours
after the push.

### Only undo what you did

If the lines were already on the device, `compare_config()` returns an empty diff and nothing is
committed. Then there's nothing to undo, and calling `rollback()` would be harmful: it would put
back the config from before the device's *last* commit, which was someone else's change. So the
undo is registered only when the diff isn't empty. (The course's first version always registered
it. A test caught it.)

### Failures and cancellation

Three ways out of the saga, and each one undoes what was done:

| What happens | How it reaches the workflow | Then |
| --- | --- | --- |
| An activity fails after its retries | `ActivityError` | Undo, return `ok=False` |
| Verification finds lines still missing | The workflow raises `ApplicationError("VerificationFailed", non_retryable=True)` | Undo, return `ok=False` |
| Someone cancels the workflow (an operator, or the orchestrator's `REQUEST_CANCEL`) | `ActivityError` whose cause is `CancelledError` if an activity was running; otherwise `asyncio.CancelledError` | Undo, then **re-raise** so the workflow ends Cancelled |

The cancellation row has a catch, and the course got it wrong at first. When a workflow is
cancelled while it waits for an activity, the cancellation shows up as **that activity's error**
(`ActivityError` with a `CancelledError` cause), not as `asyncio.CancelledError`. A plain
`except ActivityError` swallows it, and the workflow reports "failed" instead of "cancelled". The
fix is to check `err.cause`.

After a cancellation, the workflow can still run activities: the undo runs normally.

### Undos try harder

A step gives up after 3 attempts: the saga then undoes what it did, and the device is as before.
An undo gives up after 10: if it fails, the device is half-changed and a person has to step in.
So undos get more attempts.

## Walkthrough

### 1. `devices/config_push.py`: push and rollback with NAPALM

```python
# file: netops_temporal/devices/config_push.py
def push_lines(device: str, lines: list[str]) -> str:
    """Merge `lines` into the running config. Returns the diff; empty means nothing changed."""
    if lab_mode() == "mock":
        return mock_devices.push_lines(device, lines)
    with _driver(device) as driver:
        driver.load_merge_candidate(config="\n".join(lines))
        diff = driver.compare_config()
        if diff:
            driver.commit_config()
        else:
            driver.discard_config()  # nothing to do: don't leave a session open
        return diff
```

`rollback(device)` is `driver.rollback()`. `_driver` opens and closes the connection and turns
NAPALM's connection errors into the course's `DeviceUnreachableError` and `DeviceAuthError`, the
same way `napalm_eos.py` does.

The mock lab gets matching `push_lines` and `rollback`, plus one new switch for testing:
`MOCK_VERIFY_FAIL=<device>` makes pushes to that device "not stick", so verification fails.

### 2. `activities/remediation.py`

```python
# file: netops_temporal/activities/remediation.py
@activity.defn
def push_config(req: PushRequest) -> str:
    """Merge the lines and commit. Safe to retry: lines already present give an empty diff."""
    try:
        return config_push.push_lines(req.device, req.lines)
    except (DeviceAuthError, UnknownDeviceError) as err:
        raise _non_retryable(req.device, err) from err
```

`rollback_config(RollbackRequest)` is the same shape. Wrong credentials or an unknown device
won't fix themselves, so they're non-retryable (Day 3). An unreachable device is retried.

### 3. `workflows/remediation.py`: the saga

The dry-run path from Day 15 stays. Below it:

```python
# file: netops_temporal/workflows/remediation.py
        # The saga: each step that changes the device registers its undo *after* it succeeds.
        compensations: list[Callable[[], Awaitable[None]]] = []
        try:
            stamp = workflow.now().strftime("%Y%m%dT%H%M%S%fZ")
            await workflow.execute_activity(
                backup_running_config,
                BackupConfigRequest(device=req.device, timestamp=stamp),
                **STEP,
            )
            diff = await workflow.execute_activity(
                push_config, PushRequest(device=req.device, lines=req.missing_lines), **STEP
            )
            if diff:
                # Only a push that changed something gets an undo. With an empty diff, the
                # device's last commit is someone else's, and rolling back would undo theirs.
                compensations.append(
                    lambda: workflow.execute_activity(
                        rollback_config, RollbackRequest(device=req.device), **UNDO
                    )
                )
            # The diff is in history now: a permanent record of exactly what changed.
            missing = await workflow.execute_activity(
                check_config_compliance,
                ComplianceCheckRequest(device=req.device, required_lines=req.missing_lines),
                **STEP,
            )
            if missing:
                raise ApplicationError(
                    f"still missing after push: {missing}",
                    type="VerificationFailed",
                    non_retryable=True,
                )
```

The verification reuses Day 14's `check_config_compliance`: it re-reads the running config and
returns the lines that are still missing. And the push's result, the diff, is now in history: a
permanent record of exactly what changed on the device, and when.

The three ways out:

```python
# file: netops_temporal/workflows/remediation.py
        except (ActivityError, ApplicationError) as err:
            await self.compensate(compensations)
            if isinstance(err.cause, CancelledError):
                # Cancelled while an activity was running: the cancellation arrives as that
                # activity's error. Undo, then let the cancellation through.
                raise asyncio.CancelledError() from err
            return RemediationResult(
                device=req.device,
                ok=False,
                rolled_back=bool(compensations),
                error=str(err.cause if isinstance(err, ActivityError) else err),
            )
        except asyncio.CancelledError:
            # Cancelled outside an activity (by an operator, or by the orchestrator's
            # REQUEST_CANCEL policy). Undo what was done, then let the cancellation through.
            workflow.logger.warning("%s: cancelled, rolling back", req.device)
            await self.compensate(compensations)
            raise

    async def compensate(self, compensations: list[Callable[[], Awaitable[None]]]) -> None:
        # Undo in reverse order: the last change made is the first one undone.
        for undo in reversed(compensations):
            await undo()
```

A failure is a **result** (`ok=False`, with `rolled_back` saying whether anything was undone),
like the entity's operations on Day 13. The orchestrator records it and carries on with the other
devices. A cancellation is re-raised, so the workflow's status in the UI is honest: Cancelled.

### 4. The orchestrator reports it

```python
# file: netops_temporal/workflows/orchestrator.py
                if result.ok:
                    return f"config: pushed {len(result.pushed_lines)} line(s)"
                undone = "rolled back" if result.rolled_back else "nothing changed"
                return f"config: failed ({undone}): {result.error}"
```

And `starters/orchestrator.py start --apply` starts it with `dry_run=False`. Without `--apply`,
it's still a dry run.

### 5. `mock/state.py` grows up

With pushes happening for real, two remediations can push to the mock lab at the same moment
(Day 16 allows two at once, and activities run in a thread pool). The mock state file is now
changed under a lock and replaced in one step. The course found this one the hard way too: an
`--apply` run where one device's push silently erased another's.

## Run it

### Mock first

Restart the worker with one device whose pushes won't stick, and terminate any old `orchestrator`
and `upgrade-nyc-acc-01`:

```bash
LAB_MODE=mock MOCK_VERIFY_FAIL=nyc-rtr-01 uv run --env-file .env python -m netops_temporal.workers.main
```

In another terminal:

```bash
uv run --env-file .env python -m netops_temporal.starters.orchestrator start --apply
uv run --env-file .env python -m netops_temporal.starters.orchestrator status
```

Expected:

```
after 1 cycle(s):
  bos-acc-01  drifted   config: 1 missing (want 1 policy line(s) present)
                        -> config: pushed 1 line(s)
  bos-rtr-01  drifted   config: 2 missing (want 2 policy line(s) present)
                        -> config: pushed 2 line(s)
  nyc-acc-01  drifted   version: 4.32.0F (want 4.33.1F); config: 1 missing (want 1 policy line(s) present)
                        -> upgrade: started upgrade-nyc-acc-01; config: pushed 1 line(s)
  nyc-rtr-01  drifted   config: 2 missing (want 2 policy line(s) present)
                        -> config: failed (rolled back): VerificationFailed: still missing after push: ['ntp server 192.0.2.10', 'logging host 192.0.2.50']
```

`force-check`, then `status` again: `bos-acc-01` and `bos-rtr-01` are now `compliant`,
`nyc-acc-01` only has its version drift left, and `nyc-rtr-01` fails and rolls back every cycle.

Open `remediate-config-nyc-rtr-01` in the UI. The history reads like a change record:
`backup_running_config`, `push_config` (its result is the diff), `check_config_compliance` (its
result is what's still missing), then `rollback_config`.

`tests/histories/remediation_rollback.json` is a history like that one, and Day 6's replay test
now checks it too.

### Then the live lab

This changes your cEOS devices. Restart the worker without `LAB_MODE=mock`, terminate the old
orchestrator, and `start --apply` again. The diffs in history now come from EOS itself. To put a
device back afterwards, roll back its last commit:

```bash
uv run --env-file .env python -c 'from netops_temporal.devices import config_push; config_push.rollback("bos-acc-01")'
```

(Repeat for each device you changed. Later days expect the lab's original drift, so put it back.)

## Break it

1. **Forget the cancellation.** Delete the `if isinstance(err.cause, CancelledError):` block and
   run `scripts/test-solutions.sh 17`. `test_cancel_after_push_rolls_back` fails with
   `DID NOT RAISE`: the workflow "completed" with `ok=False` instead of ending Cancelled. Put it
   back.
2. **Always register the undo.** Remove the `if diff:` and run the tests:
   `test_empty_diff_registers_no_rollback` fails. The rollback undid an earlier commit that had
   nothing to do with this remediation.
3. **Cancel one yourself.** Start the worker with `LAB_MODE=mock MOCK_CLI_DELAY=10` (every config
   read takes 10 s), start a remediation with `temporal workflow start --type ConfigRemediationWorkflow --task-queue netops-orchestration --workflow-id remediate-config-bos-acc-01 --input '{"device": "bos-acc-01", "missing_lines": ["ntp server 192.0.2.10"], "dry_run": false}'`,
   and during the verification `temporal workflow cancel --workflow-id remediate-config-bos-acc-01`.
   The history ends with `rollback_config` and then **WorkflowExecutionCanceled**.
4. **Kill the worker mid-saga.** Same setup; this time kill the worker during the verification and
   start it again. The workflow carries on from where it was. If it then fails, it still knows
   the push happened and rolls it back: the list of undos was rebuilt from history.

## Check yourself

1. In a saga, when is an undo registered: before its step or after? Why?
2. Why does the workflow check `err.cause` for `CancelledError` inside `except ActivityError`?
3. Why is the rollback skipped when the push's diff is empty?
4. Why do undos get more retry attempts than steps?
5. A worker crashes after the push and before the verification. What happens?

<details>
<summary>Answers</summary>

1. After it succeeds. If the step failed, it changed nothing, so there's nothing to undo; and an
   undo of a change that didn't happen can do damage (see question 3).
2. A cancellation that arrives while the workflow waits for an activity is delivered as that
   activity's error, an `ActivityError` caused by `CancelledError`. Without the check, the
   handler treats it as an ordinary failure, and the workflow doesn't end Cancelled.
3. An empty diff means nothing was committed, so the device's last commit is someone else's.
   `rollback()` would undo their change.
4. If a step gives up, the saga undoes what came before and the device is back where it started.
   If an undo gives up, the device is left half-changed and someone has to fix it by hand.
5. A new worker replays history: the backup and push return their recorded results (the device
   isn't touched again), the undo is registered again, and the verification runs. If it fails,
   the rollback happens as normal.

</details>

## Solution

[`solutions/day-17/`](../../../solutions/day-17/): new `devices/config_push.py` and
`activities/remediation.py`; the saga in `workflows/remediation.py`; the orchestrator reports
failed remediations; `--apply` in `starters/orchestrator.py`; `MOCK_VERIFY_FAIL`, `push_lines`
and `rollback` in the mock lab; a locked, atomic `mock/state.py`. `tests/test_saga.py` checks the
activities, a clean push, a failed verification that rolls back, a device that's down (nothing
to undo), an auth failure (not retried), an empty diff (no rollback) and a cancellation after the
push (rolled back, then Cancelled). `tests/histories/remediation_rollback.json` is replayed.
