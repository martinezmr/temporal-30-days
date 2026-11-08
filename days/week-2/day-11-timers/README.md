# Day 11 — Durable timers: approval deadlines and maintenance windows

[← Day 10](../day-10-updates/README.md) · [Day 12 →](../day-12-continue-as-new/README.md)

**Time:** 60–90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-11/`](../../../solutions/day-11/)

## Why today matters

Real changes wait. A change is requested at 15:00, needs a manager's approval within the hour,
and may only run in the 02:00–04:00 UTC maintenance window. In a script, "wait until 02:00" is a
`sleep` in a process that has to survive for 11 hours: through laptop lids, deploys and reboots.
In practice people use cron, a ticketing system, and someone's memory.

Temporal's answer is the **durable timer**: a wait that lives on the server, not in your process.
Today you build `ChangeWindowWorkflow`, which waits for an approval with a deadline, then sleeps
until the maintenance window, then runs the change. Kill the worker in the middle of either wait
and nothing is lost.

## Concept

### A timer lives on the server

When workflow code sleeps, the worker doesn't sit there counting. It tells the server "wake me at
T" (**TimerStarted** in history), finishes its workflow task, and forgets about the workflow.
At T the server records **TimerFired** and schedules a workflow task. Whichever worker picks it up
replays the history and carries on from the line after the sleep.

So a timer:

- costs nothing while it waits (no thread, no process, no polling);
- can be seconds or months long;
- fires on time even if every worker is down at that moment. The workflow continues when one
  comes back.

Network analogy: `commit timer` on EOS, or a scheduled `reload in 10`. The device itself keeps the
timer; your SSH session can drop and it still fires.

### Three ways to wait on a timer

| Code | Waits for |
| --- | --- |
| `await workflow.sleep(timedelta(hours=11))` | Exactly that long |
| `await asyncio.sleep(...)` inside a workflow | The same thing: the SDK turns it into a durable timer |
| `await workflow.wait_condition(fn, timeout=...)` | Until `fn()` is true, or the time is up (raises `TimeoutError`) |

The last one is the "deadline" pattern: wait for an approval signal, but give up at the deadline.

### Workflow time: `workflow.now()`

Calculating "how long until 02:00?" needs the current time. Inside a workflow you must use
`workflow.now()`, never `datetime.now()`:

- `workflow.now()` is the time of the current workflow task, recorded in history. On replay it
  returns the same value it did the first time, so the calculation comes out the same, and the
  workflow creates the same timer.
- `datetime.now()` returns a different value on replay, so the timer length would differ. The
  sandbox blocks it (you'll see the error in **Break it**).

### Keep the arithmetic in a pure function

"When does the next window start?" is plain date arithmetic. It goes in an ordinary function,
`next_window_start(now, window)`, that takes the time as an argument instead of reading a clock.
That makes it deterministic (safe to call from a workflow), and it can be unit-tested with any
`now` you like, including the edge cases: inside the window, just after it, windows that cross
midnight.

## Walkthrough

### 1. `models.py`: windows, requests, results

```python
# file: netops_temporal/models.py
class MaintenanceWindow(BaseModel):
    """A daily window, in UTC, when changes are allowed. It may cross midnight."""

    start_hour_utc: int = Field(ge=0, le=23)
    duration_hours: int = Field(ge=1, le=24)


class ChangeWindowRequest(BaseModel):
    device: str
    window: MaintenanceWindow
    approval_timeout_minutes: int = Field(default=60, ge=1)
```

`Field(ge=..., le=...)` makes Pydantic reject a `start_hour_utc` of 24 or a zero-minute deadline
when the request is built, before any workflow starts.

### 2. `windows.py`: the arithmetic

```python
# file: netops_temporal/windows.py
def next_window_start(now: datetime, window: MaintenanceWindow) -> datetime:
    """When the change may run: `now` if a window is open, else the next window's start.

    Pure: the same inputs always give the same answer. That's what makes it safe to call
    inside a workflow (with workflow.now(), never datetime.now()).
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware (use workflow.now())")
    today_start = now.replace(hour=window.start_hour_utc, minute=0, second=0, microsecond=0)
    length = timedelta(hours=window.duration_hours)
    # Yesterday's window can still be open after midnight (e.g. 22:00-02:00).
    for start in (today_start - timedelta(days=1), today_start):
        if start <= now < start + length:
            return now
    return today_start if now < today_start else today_start + timedelta(days=1)
```

### 3. `workflows/change_window.py`: deadline, then window, then act

```python
# file: netops_temporal/workflows/change_window.py
    @workflow.run
    async def run(self, req: ChangeWindowRequest) -> ChangeWindowResult:
        # 1. Wait for a human, but not forever. The deadline is a timer on the server, so it
        #    fires on time even if no worker is running at that moment.
        try:
            await workflow.wait_condition(
                lambda: self.decision is not None,
                timeout=timedelta(minutes=req.approval_timeout_minutes),
            )
        except TimeoutError:
            return ChangeWindowResult(
                device=req.device, approved=False, reason="approval timed out"
            )
```

```python
# file: netops_temporal/workflows/change_window.py
        # 2. Sleep until the window opens. workflow.now() is the workflow's clock: on replay it
        #    returns the time recorded in history, so this calculation always comes out the same.
        self._stage = "waiting for window"
        wait = next_window_start(workflow.now(), req.window) - workflow.now()
        if wait > timedelta(0):
            await workflow.sleep(wait)

        # 3. The change itself. Here a config backup stands in for it; Week 3 pushes config.
        self._stage = "running"
        ran_at = workflow.now()
        path = await workflow.execute_activity(
            backup_running_config,
            BackupConfigRequest(device=req.device, timestamp=ran_at.strftime("%Y%m%dT%H%M%SZ")),
            start_to_close_timeout=timedelta(seconds=60),
        )
```

- If the window is already open, `wait` is zero and there's no timer at all.
- The "change" is the Day 7 backup activity for now. On Day 17 a real config push takes its
  place.

```python
# file: netops_temporal/workflows/change_window.py
    @workflow.signal
    def approve(self, approver: str) -> None:
        if self.decision is None:  # the first decision wins
            self.decision = (True, approver)
```

`reject` is the same with `False`. A `stage` query reports where the workflow is waiting.

### 4. Register it and use the starter

`ChangeWindowWorkflow` goes into `WORKFLOWS`. `starters/change_window.py` has `request`,
`approve`, `reject`, `stage` and `result` actions:

```python
# file: netops_temporal/starters/change_window.py
    # get_workflow_handle_for knows the workflow's result type, so result() returns a model.
    handle = client.get_workflow_handle_for(ChangeWindowWorkflow.run, workflow_id)
```

## Run it

Restart the worker. Request a change whose window is open **right now** (use the current UTC
hour, e.g. `date -u +%H`), approve it, and get the result:

```bash
uv run --env-file .env python -m netops_temporal.starters.change_window bos-rtr-01 request "$(date -u +%-H)" 1
uv run --env-file .env python -m netops_temporal.starters.change_window bos-rtr-01 stage
uv run --env-file .env python -m netops_temporal.starters.change_window bos-rtr-01 approve alice
uv run --env-file .env python -m netops_temporal.starters.change_window bos-rtr-01 result
```

Expected:

```
started change-window-bos-rtr-01; waiting for approval
awaiting approval
sent approve from alice
device='bos-rtr-01' approved=True reason='approved by alice' ran_at=datetime.datetime(...) backup_path='output/backups/bos-rtr-01/....cfg'
```

The history shows **TimerStarted** (the approval deadline), then
**WorkflowExecutionSignaled** (the approval), then **TimerCanceled**: the condition came true
first, so the SDK cancelled the deadline timer. There's no window timer, because the window was
already open.

Now request one for a window a few hours away (`request bos-acc-01 <hour> 2`), approve it, and
look at the UI: status **Running**, a pending timer, and `stage` says `waiting for window`. You
can leave it, or terminate it.

The tests show the long waits without waiting: `scripts/test-solutions.sh 11` runs a 60-minute
deadline and a sleep until 02:00 in about a second, because the test server skips time when the
workflow is only waiting.

## Break it

1. **Kill the worker during the deadline.** Request a change with a 1-minute deadline
   (`request nyc-rtr-01 <hour> 1 1`) and stop the worker at once. Wait over a minute. History
   shows **TimerFired** at exactly the deadline, with no worker running. Start the worker again:
   `result` prints `approved=False reason='approval timed out'`.
2. **Approve too late.** Now `approve nyc-rtr-01 bob`. It fails with
   `RPCError: workflow execution already completed`. There's nothing left to signal.
3. **Use the wrong clock.** In `run`, replace the `workflow.now()` calls with
   `datetime.datetime.now(datetime.UTC)`, restart the worker, request and approve. The workflow
   doesn't fail; it gets stuck. The worker log shows
   `RestrictedWorkflowAccessError: Cannot access datetime.datetime.now.__call__ from inside a workflow`,
   and the workflow task is retried over and over. Fix the code, restart the worker, and the same
   workflow carries on. Put it back.
4. **Two approvers disagree.** Request a change, then `reject ... alice` and `approve ... bob`
   quickly. The result says `rejected by alice`: the first decision wins, because the handler
   ignores later ones.

## Check yourself

1. Where does a timer live while it's waiting, and what's it costing you?
2. What happens if a timer fires while no worker is running?
3. Why `workflow.now()` and not `datetime.now()`?
4. Why is `next_window_start` a separate function that takes `now` as an argument?
5. How does the test check a 60-minute deadline in about a second?

<details>
<summary>Answers</summary>

1. On the Temporal server, as a **TimerStarted** event and a server-side timer. It costs nothing on
   the worker: no thread, no process.
2. The server still records **TimerFired** on time and schedules a workflow task. The workflow
   continues as soon as a worker picks it up.
3. `workflow.now()` comes from history, so it returns the same value on replay and the workflow
   makes the same decisions. `datetime.now()` would differ on replay, so the sandbox blocks it.
4. So it's deterministic and testable: no hidden clock, and unit tests can pass any time,
   including edge cases like windows that cross midnight.
5. The time-skipping test server jumps ahead whenever every workflow is just waiting on timers.

</details>

## Solution

[`solutions/day-11/`](../../../solutions/day-11/): new `windows.py`,
`workflows/change_window.py` and `starters/change_window.py`; `MaintenanceWindow`,
`ChangeWindowRequest` and `ChangeWindowResult` in `models.py`. `tests/test_change_window.py`
unit-tests the window arithmetic (including midnight) and, with time skipping, the deadline,
rejection and approve-then-wait paths.
