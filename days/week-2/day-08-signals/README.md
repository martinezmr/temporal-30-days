# Day 08 — Signals: a workflow you can talk to

[← Week 2](../README.md) · [Day 09 →](../day-09-queries/README.md)

**Time:** 60–90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-08/`](../../../solutions/day-08/)

## Why today matters

Every workflow in Week 1 started, did its job and finished. A lot of network operations don't
look like that. A device watch runs for weeks. A change waits for an approval. A compliance loop
runs until someone stops it. While these run, people need to talk to them: "pause the checks on
`bos-rtr-01`, we're working on it", "check it *now*, I just changed something".

The old way is a cron job plus a flag file, or a database row the script polls. Temporal has this
built in. Today you build `DeviceWatchWorkflow`: it checks a device's facts every few minutes,
forever, and takes orders while it runs. The orders are **signals**.

## Concept

### A workflow is a long-lived object with state

A workflow isn't only a function that runs top to bottom. Its class can hold state in ordinary
attributes (`self.paused`, `self.checks`) that live as long as the workflow does: days, months.
That state is never saved anywhere. It's rebuilt by replay (Day 4), because everything that
changes it is in the event history.

Think of a change ticket that's open for a week: people add comments to it, and the ticket's
current status is whatever all those comments add up to.

### Signals: fire-and-forget messages into a running workflow

A **signal** is a named message, with optional arguments, sent to one workflow by its ID:

- The server writes it into the workflow's history (**WorkflowExecutionSignaled**) and returns
  right away. The sender doesn't wait for the workflow to react, and gets nothing back.
- On the worker, the SDK calls the workflow's matching `@workflow.signal` method. The method
  changes state. It must not block or call activities.
- If no worker is running, the signal waits in history, and is handled when a worker picks the
  workflow up again. Nothing is lost.

Network analogy: an SNMP trap or a syslog message. You send it and move on; whoever receives it
decides what to do.

### `wait_condition`: "block until the state says go"

A signal handler only flips state. The run loop has to *notice*. That's
`await workflow.wait_condition(lambda: ...)`: it blocks the workflow until the lambda returns
true. The SDK re-checks the lambda every time something happens in the workflow, such as a signal
arriving.

With `timeout=`, it raises `TimeoutError` if the condition is still false when time is up. That
gives you "sleep for 5 minutes, but wake up early if someone asks", which is exactly what a device
watch needs. The timeout is a **durable timer** on the server (you'll see **TimerStarted** in
history), so it survives worker restarts. Day 11 is all about timers.

### Where the workflow is waiting matters

The loop below waits in two places: "until not paused" before each check, and "until a check is
requested, or the interval passes" after each check. A signal only has an effect when the
workflow is waiting on a condition that signal can change. You'll see this in **Run it**: `resume`
doesn't make a check happen right away if the workflow is in its interval wait.

## Walkthrough

### 1. `models.py`: the input

```python
# file: netops_temporal/models.py
class WatchRequest(BaseModel):
    """Input to DeviceWatchWorkflow: which device, and how often to check it."""

    device: str
    interval_seconds: int = 300
```

### 2. `workflows/watch.py`: state, a loop, and three signals

```python
# file: netops_temporal/workflows/watch.py
@workflow.defn
class DeviceWatchWorkflow:
    def __init__(self) -> None:
        # Workflow state is plain attributes. Signals change it; the run loop reacts to it.
        self.paused = False
        self.check_requested = False
        self.checks = 0
        self.last_facts: DeviceFacts | None = None
```

`__init__` runs once when the workflow starts (and again on every replay, which is fine: it only
sets defaults).

```python
# file: netops_temporal/workflows/watch.py
    @workflow.run
    async def run(self, req: WatchRequest) -> None:
        while True:
            # Blocks (durably, for as long as it takes) until nobody has paused us.
            await workflow.wait_condition(lambda: not self.paused)
            self.last_facts = await workflow.execute_activity(
                get_device_facts,
                FactsRequest(device=req.device),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            self.checks += 1
            self.check_requested = False
            try:
                # Sleep until the next check is due, but wake early if someone asks.
                await workflow.wait_condition(
                    lambda: self.check_requested,
                    timeout=timedelta(seconds=req.interval_seconds),
                )
            except TimeoutError:
                pass  # The normal case: the interval passed with no request.
```

- `while True` in a workflow is fine. Every pass waits on something durable, so the worker isn't
  busy; the workflow just sits in history between checks. (Each pass *does* add events to
  history, which can't grow forever. Day 12 fixes that with continue-as-new.)
- `get_device_facts` is the Day 3 activity, reused as-is.
- `maximum_attempts=3` keeps one bad check from retrying for long. Today an unreachable device
  still fails the whole watch after 3 attempts; tomorrow you'll catch that and keep watching.

```python
# file: netops_temporal/workflows/watch.py
    # A signal handler only changes state. It returns nothing and must not block.
    @workflow.signal
    def pause(self) -> None:
        self.paused = True

    @workflow.signal
    def resume(self) -> None:
        self.paused = False

    @workflow.signal
    def check_now(self) -> None:
        self.check_requested = True
```

The signal's name is the method name (`pause`, `resume`, `check_now`). That's what the CLI uses.

### 3. Register the workflow

```python
# file: netops_temporal/workers/main.py
WORKFLOWS = [
    HelloWorkflow,
    GetFactsWorkflow,
    ShowTechWorkflow,
    ConfigBackupWorkflow,
    DeviceWatchWorkflow,
]
```

### 4. `starters/watch.py`: start a watch, or signal one

```python
# file: netops_temporal/starters/watch.py
SIGNALS = {
    "pause": DeviceWatchWorkflow.pause,
    "resume": DeviceWatchWorkflow.resume,
    "check-now": DeviceWatchWorkflow.check_now,
}
```

```python
# file: netops_temporal/starters/watch.py
    else:
        # A handle is just "the workflow with this ID". Sending a signal doesn't wait for
        # the workflow to do anything: it's written into history, and that's it.
        await client.get_workflow_handle(workflow_id).signal(SIGNALS[action])
        print(f"sent {action} to {workflow_id}")
```

Passing the method (`DeviceWatchWorkflow.pause`) instead of the string `"pause"` lets your editor
and type checker catch typos. You'll see why that matters in **Break it**.

## Run it

Restart the worker (it has a new workflow), then in another terminal:

```bash
uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01
uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01 check-now
uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01 pause
```

Expected:

```
started watch-bos-rtr-01
sent check-now to watch-bos-rtr-01
sent pause to watch-bos-rtr-01
```

Open `watch-bos-rtr-01` in the UI (status **Running**, and it stays that way) and look at the
history:

```
ActivityTaskCompleted       ← first check
TimerStarted                ← the 300 s interval wait
WorkflowExecutionSignaled   ← check_now
ActivityTaskCompleted       ← the extra check
TimerStarted                ← a new interval wait
WorkflowExecutionSignaled   ← pause
```

Click a **WorkflowExecutionSignaled** event to see the signal name. The workflow is now paused,
but it's still in its interval wait. When that timer fires, it loops round and blocks on "until
not paused". Send `resume` and the next check happens when the current interval ends, not right
away, because of where the workflow was waiting.

The same signals work from the CLI:

```bash
temporal workflow signal --workflow-id watch-bos-rtr-01 --name check_now
```

Note the CLI takes the signal's real name, `check_now`, not the starter's `check-now`.

When you're done: `temporal workflow terminate --workflow-id watch-bos-rtr-01`.

## Break it

1. **Signal while no worker is running.** Start a watch, `pause` it, then stop the worker. Send
   `resume`. The starter still says `sent resume`, and history shows **WorkflowExecutionSignaled**
   with no worker anywhere. Start the worker again. About 10 seconds later, history shows
   **WorkflowTaskTimedOut** and then the task completing. The server first offered the task to
   the old worker that you killed (Temporal keeps sending a workflow to the same worker while
   it's alive, for speed), timed out, and then handed it to the new one. The signal was never
   lost.
2. **Signal a workflow that doesn't exist.** `... starters.watch nope-01 pause` fails with
   `RPCError: workflow not found for ID: watch-nope-01`. Signals go to a workflow ID, and the ID
   has to exist (Day 10 shows how to start-if-missing).
3. **Misspell a signal name.** `temporal workflow signal --workflow-id watch-bos-rtr-01 --name chek_now`.
   It says `Signal workflow succeeded`. Nothing happens on the worker: no check, no error, not
   even a warning in its log. The Python SDK holds signals it has no handler for, in case a
   handler is added later. That's why the starter passes `DeviceWatchWorkflow.check_now`
   instead of a string.

## Check yourself

1. What does the sender of a signal get back?
2. Where is a signal stored if no worker is running?
3. Why must a signal handler not call an activity or sleep?
4. What does `wait_condition(..., timeout=...)` give you that `workflow.sleep` alone doesn't?
5. You sent `resume` and nothing happened for four minutes. Why?

<details>
<summary>Answers</summary>

1. Nothing but "accepted": the server wrote it into history. It doesn't wait for the workflow to
   do anything, and returns no value. (Day 9's queries and Day 10's updates do return values.)
2. In the workflow's event history, as **WorkflowExecutionSignaled**. A worker handles it when it
   next runs the workflow.
3. Signal handlers are for changing state, quickly. The run loop does the work. If handlers did
   I/O, two signals could interleave halfway through each other's work. (Async handlers can do
   more, carefully. Day 13 shows that with a lock.)
4. An early wake-up. `workflow.sleep` waits the full time; `wait_condition` with a timeout waits
   *up to* that time, and returns as soon as the condition is true.
5. The workflow was in its interval wait, `wait_condition(lambda: self.check_requested, ...)`,
   which `resume` doesn't affect. The next check happens when the timer fires. Send `check_now`
   to check immediately.

</details>

## Solution

[`solutions/day-08/`](../../../solutions/day-08/): new `workflows/watch.py` and
`starters/watch.py`; `WatchRequest` in `models.py`; the workflow registered in the worker.
`tests/test_watch.py` checks the first check, a `check_now` signal, the interval timer (with
time skipping), and pause/resume.
