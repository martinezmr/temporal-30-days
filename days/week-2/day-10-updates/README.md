# Day 10 — Updates, validators, and "start it if it isn't running"

[← Day 09](../day-09-queries/README.md) · [Day 11 →](../day-11-timers/README.md)

**Time:** 60–90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-10/`](../../../solutions/day-10/)

## Why today matters

An operator wants the watch on `nyc-rtr-01` to check every minute during a change window. With
what you have so far, they'd send a signal and then query to see whether it took effect, and a
typo like `5` seconds (which would hammer the device) would be accepted and written into history
before anything could object.

Today you add an **update**: a request that changes the workflow *and* returns an answer, with a
**validator** that rejects bad input before it touches history. You'll also learn the two
"with-start" calls, which remove the classic race "is the workflow already running? If not,
start it, then send the message".

## Concept

### Updates: a request with a response

An **update** is a method marked `@workflow.update`. The caller sends it and **waits** for the
result:

- It can change state, like a signal.
- It returns a value, like a query, and that value comes back to the caller.
- If it raises, the caller gets the error.
- It's recorded in history: **WorkflowExecutionUpdateAccepted**, then
  **WorkflowExecutionUpdateCompleted** with the result.

Network analogy: a commit with a confirmation. You don't fire the change off and hope; you get
back "done, and here's the result".

### Validators: reject before anything is written

An update can have a **validator**, a method decorated with `@<update>.validator`. It runs on the
worker *before* the update is accepted:

- If it raises, the update is **rejected**. The caller gets the error, and **nothing** about the
  update is written to history.
- If it returns normally, the update is accepted and the handler runs.
- It must not change state. It only says yes or no.

This is input validation that leaves no trace: a fat-fingered `5` never becomes part of the
workflow's permanent record.

### Signal, query or update?

| You want to... | Use |
| --- | --- |
| Tell the workflow something, and not wait | Signal |
| Read its state, with no side effects | Query |
| Change something and know it worked (or why it didn't) | Update |
| Reject bad requests without a trace | Update with a validator |

### "Start it if it isn't running": the with-start calls

Sending a message to a workflow ID that isn't running fails (Day 8, Break it 2). The naive fix,
"check if it's running, start it if not, then send", has a race: two operators can both see
"not running" and both try to start it. Temporal does both steps in **one** call:

- **Signal-with-start**: `client.start_workflow(..., start_signal="check_now")`. If the workflow
  is running, it gets the signal. If not, it's started, and the signal is delivered as it starts.
- **Update-with-start**: `client.execute_update_with_start_workflow(update, arg,
  start_workflow_operation=WithStartWorkflowOperation(...))`. Same idea, but you also get the
  update's result back. The operation needs an `id_conflict_policy`.
  `WorkflowIDConflictPolicy.USE_EXISTING` means "if it's already running, use that one".

### `@workflow.init`: set up state before any handler runs

With update-with-start, the update can run **before** your `run` method does. If `run` is where
you set `self.device`, the update would see an empty device name. (The course's own test caught
exactly this.) The fix is `@workflow.init`: it makes `__init__` receive the same input as `run`,
so state is ready before any signal, query or update handler is called.

## Walkthrough

### 1. `models.py`

```python
# file: netops_temporal/models.py
class SetIntervalRequest(BaseModel):
    """Input to the DeviceWatchWorkflow.set_interval update."""

    interval_seconds: int
```

`WatchStatus` gains `interval_seconds: int = 300`, so the status shows it.

### 2. `workflows/watch.py`: `@workflow.init`

```python
# file: netops_temporal/workflows/watch.py
class DeviceWatchWorkflow:
    # @workflow.init: __init__ gets the workflow's input, so state is set up before any
    # handler runs. With update-with-start, the update can run before `run` does.
    @workflow.init
    def __init__(self, req: WatchRequest) -> None:
```

```python
# file: netops_temporal/workflows/watch.py
        self.device = req.device
        self.interval_seconds = req.interval_seconds
```

The interval is now state, not read from `req` each time, so an update can change it. The wait
uses `timeout=timedelta(seconds=self.interval_seconds)`.

### 3. The update and its validator

```python
# file: netops_temporal/workflows/watch.py
    # An update changes state *and* returns a result to the caller, who waits for it.
    @workflow.update
    def set_interval(self, req: SetIntervalRequest) -> WatchStatus:
        # The wait that's already running keeps its timer; the new interval applies from the
        # next one.
        self.interval_seconds = req.interval_seconds
        return self.status()

    # The validator runs first. If it raises, the update is rejected and nothing about it is
    # written to history. It must not change state.
    @set_interval.validator
    def validate_set_interval(self, req: SetIntervalRequest) -> None:
        if not 30 <= req.interval_seconds <= 86400:
            raise ValueError("interval must be 30..86400 seconds")
```

- The update returns `self.status()`, the same snapshot the query returns, so the caller sees
  the new state immediately.
- A timer that's already running can't be changed. The new interval applies from the next wait.
  (If you wanted it to apply at once, you'd also wake the wait with a flag, like `check_now` does.)

### 4. `starters/watch.py`: update-with-start and signal-with-start

```python
# file: netops_temporal/starters/watch.py
async def set_interval(client: Client, device: str, seconds: int) -> None:
    # Update-with-start: one call that starts the watch if needed, then runs the update on
    # it and waits for the result. USE_EXISTING means "if it's already running, use that one".
    start_op = WithStartWorkflowOperation(
        DeviceWatchWorkflow.run,
        WatchRequest(device=device),
        id=f"watch-{device}",
        task_queue=ORCHESTRATION_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    status = await client.execute_update_with_start_workflow(
        DeviceWatchWorkflow.set_interval,
        SetIntervalRequest(interval_seconds=seconds),
        start_workflow_operation=start_op,
    )
```

```python
# file: netops_temporal/starters/watch.py
    elif action == "check-now":
        # Signal-with-start: signal the watch, starting it first if it isn't running.
        await client.start_workflow(
            DeviceWatchWorkflow.run,
            WatchRequest(device=device),
            id=workflow_id,
            task_queue=ORCHESTRATION_TASK_QUEUE,
            start_signal="check_now",
        )
```

`check-now` no longer needs the watch to exist. Neither does `interval`.

## Run it

Restart the worker. Make sure no watch is running for `nyc-rtr-01`
(`temporal workflow terminate --workflow-id watch-nyc-rtr-01` if needed), then:

```bash
uv run --env-file .env python -m netops_temporal.starters.watch nyc-rtr-01 interval 60
uv run --env-file .env python -m netops_temporal.starters.watch nyc-rtr-01 interval 90
```

The first call starts the watch *and* sets the interval. Its status shows `"checks": 0`: the
update ran before the first check did, which is exactly why `@workflow.init` matters. The second
call finds the running watch and updates it (`"interval_seconds": 90`, `"checks": 1`).

In the UI there's still only one `watch-nyc-rtr-01`, and its history has two
**WorkflowExecutionUpdateAccepted** / **WorkflowExecutionUpdateCompleted** pairs. Click one to
see the update's input and result.

## Break it

1. **A bad interval.** `... starters.watch nyc-rtr-01 interval 5`. The starter fails with
   `WorkflowUpdateFailedError: Workflow update failed`, caused by
   `ApplicationError: ValueError: interval must be 30..86400 seconds`. Look at the history: no
   new events at all. The validator turned it away before anything was written.
2. **Update with no worker.** Stop the worker and run `interval 120`. The command just waits: an
   update needs a worker to run the validator and the handler. Start the worker in another
   terminal, and within a few seconds the waiting command prints the new status. (A signal would
   have returned at once; a query would have failed.)
3. **With-start, twice.** Run `check-now` for a device with no watch: it starts one. Run it again:
   the same watch gets a second `check_now` and does another check. Two calls, one workflow, no
   race.
4. **Forget `@workflow.init`.** Remove the decorator, change `__init__` back to taking no
   arguments, and set `self.device` and `self.interval_seconds` at the top of `run` instead.
   Then terminate the watch and run `interval 60` (update-with-start) again. The status comes back
   with `"device": ""`: the update ran before `run` had set anything. Put it back.

## Check yourself

1. What's the difference between an update's validator raising and its handler raising?
2. Why must a validator not change state?
3. Two operators run `interval 60` for the same device at the same moment, and no watch is
   running. How many watches end up running?
4. Why does `"checks": 0` show up in the first update-with-start response?
5. When should you use a signal instead of an update?

<details>
<summary>Answers</summary>

1. A validator raising **rejects** the update: nothing goes into history. A handler raising
   happens after the update was accepted, so the history records the update and its failure.
2. Because a rejected update leaves no trace in history. Any state it changed couldn't be
   rebuilt on replay, and the workflow would behave differently after a restart.
3. One. Update-with-start with `USE_EXISTING` is a single atomic call on the server: one call
   starts the workflow, and the other finds it running and uses it.
4. The update was delivered with the start, and ran before the workflow's first activity. The
   first check happens right after.
5. When the sender doesn't need an answer and shouldn't have to wait, for example a trap-like
   notification, or when no worker might be running and you still want the message stored.

</details>

## Solution

[`solutions/day-10/`](../../../solutions/day-10/): `SetIntervalRequest` and
`WatchStatus.interval_seconds` in `models.py`; `@workflow.init`, the `set_interval` update and its
validator in `workflows/watch.py`; update-with-start and signal-with-start in
`starters/watch.py`. `tests/test_watch.py` adds the update, the rejected-and-not-in-history
case, the new interval taking effect, and both with-start calls.
