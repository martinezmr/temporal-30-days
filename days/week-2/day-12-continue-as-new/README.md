# Day 12 — Continue-as-new: run forever without growing forever

[← Day 11](../day-11-timers/README.md) · [Day 13 →](../day-13-entity-workflows/README.md)

**Time:** 60 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-12/`](../../../solutions/day-12/)

## Why today matters

The device watch is a `while True` loop, and every pass adds about eleven events to its history:
an activity scheduled, started and completed, a timer, workflow tasks. Checking every 5 minutes,
that's over 3,000 events a day. Event history has a hard limit, and long before reaching it,
every worker that picks the workflow up has to replay the whole thing, which gets slower and
slower.

Today you make the watch **continue-as-new**: every so often it ends its current run and starts a
fresh one with the same workflow ID, handing over its state. To operators it's one watch that
never stops. To Temporal it's a chain of short runs.

## Concept

### History can't grow forever

A single workflow run's history is capped at **51,200 events or 50 MB**. The server warns well
before that, and if a run hits the limit, the server terminates it. Long before that, history size
hurts: replay time grows with it, and every workflow task on a fresh worker pays that cost.

### Continue-as-new: end this run, start the next

`workflow.continue_as_new(arg)` does three things at once, atomically:

1. It completes the current run with the status **ContinuedAsNew**.
2. It starts a new run with the **same workflow ID**, passing `arg` as its input.
3. The new run starts with an **empty history**.

What carries over: the workflow ID, and whatever you put in `arg`. What doesn't: everything else
in memory. So any state worth keeping (the check count, the last facts, `paused`, the interval)
has to go into the new run's input.

Network analogy: log rotation. `messages` becomes `messages.1` and a new, empty `messages` takes
its place. It's the same log as far as anyone reading it is concerned.

### When to continue

- `workflow.info().is_continue_as_new_suggested()` turns true when the server thinks history is
  getting big. Always check it.
- Your own limit (here, `max_checks_per_run`) keeps runs predictably short, and lets you see
  continue-as-new happen in a demo in a minute instead of days.

### Finish handlers first

A signal or update handler might still be in the middle of something when you decide to
continue-as-new. `await workflow.wait_condition(workflow.all_handlers_finished)` waits until none
are running, so nothing is cut off. Signals that arrive while the run is ending aren't lost: the
server makes the run handle them first, and the state they change gets handed over.

### Handles and runs

A workflow ID now has several runs. A handle without a run ID, from
`client.get_workflow_handle("watch-bos-rtr-01")` or the one `start_workflow` returns, always
means the **latest** run, so signals, queries and updates follow the chain. To reach one
particular run, pass its run ID (`get_workflow_handle(id, run_id=...)`, or `--run-id` in the CLI):
you get that run's final state, frozen.

## Walkthrough

### 1. `models.py`: the state that crosses over

```python
# file: netops_temporal/models.py
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
```

Every new field has a default (Day 3), so starters that only pass `device` keep working, and so do
watches started before today's change.

### 2. `workflows/watch.py`: start from the handed-over state

```python
# file: netops_temporal/workflows/watch.py
        # A continued run starts from the state the previous run handed over (Day 12).
        self.paused = req.paused
        self.check_requested = False
        self.checks = req.checks_so_far
        self.last_facts: DeviceFacts | None = req.last_facts
        self.last_error: str | None = req.last_error
```

This is the payoff of Day 10's `@workflow.init`: `__init__` already receives the input.

### 3. Continue-as-new at the end of a pass

```python
# file: netops_temporal/workflows/watch.py
            # Day 12: every pass adds events to history. Before it gets too long, end this run
            # and start a fresh one with the same workflow ID, handing over the state.
            checks_this_run += 1
            if (
                workflow.info().is_continue_as_new_suggested()
                or checks_this_run >= req.max_checks_per_run
            ):
                # Let any signal or update handler that's still running finish first.
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(
                    WatchRequest(
                        device=self.device,
                        interval_seconds=self.interval_seconds,
                        checks_so_far=self.checks,
                        last_facts=self.last_facts,
                        last_error=self.last_error,
                        paused=self.paused,
                        max_checks_per_run=req.max_checks_per_run,
                    )
                )
```

- It goes **after** the interval wait, so the new run's first action, a check, happens at the
  right time instead of straight after the previous one.
- `continue_as_new` never returns. It raises a special exception that ends the run.
- `checks_this_run` is a local variable, not state: it starts at 0 in every run.

### 4. The starter can set a short run

`start` now takes optional interval and max-checks arguments, so you can watch runs roll over:

```python
# file: netops_temporal/starters/watch.py
        interval, max_checks = (int(a) for a in (*args, 300, 500)[:2])
```

## Run it

Restart the worker, terminate any existing `watch-bos-rtr-01`, then:

```bash
uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01 start 30 2
```

Wait a little over a minute, then:

```bash
uv run --env-file .env python -m netops_temporal.starters.watch bos-rtr-01 status
temporal workflow list --query 'WorkflowId="watch-bos-rtr-01"'
```

Expected: `"checks": 3` (or more) and `"interval_seconds": 30`, carried across runs, and a list
like:

```
  Status          WorkflowId        Type                 StartTime
  Running         watch-bos-rtr-01  DeviceWatchWorkflow  15 seconds ago
  ContinuedAsNew  watch-bos-rtr-01  DeviceWatchWorkflow  1 minute ago
```

In the UI, open the closed run: its last event is **WorkflowExecutionContinuedAsNew**, and the
page links to the next run. Open the running one: its **WorkflowExecutionStarted** input holds the
handed-over state (`checks_so_far`, `last_facts`, ...).

The replay test now includes `tests/histories/watch_can.json`, a real run that ended in
continue-as-new.

## Break it

1. **Forget to hand over a field.** Remove `checks_so_far=self.checks` from the
   `continue_as_new` call and restart the worker. After each roll-over, `status` shows `checks`
   back at 1. The test `test_continue_as_new_carries_state` fails the same way. Put it back.
2. **Roll over every check.** Start a watch with `start 30 1`. Every pass is now a new run.
   `temporal workflow list --query 'WorkflowId="watch-bos-rtr-01"'` grows by one line every 30 s,
   while `status` keeps counting up. Pause it: the pause carries across runs too.
3. **Query an old run.** Copy the run ID of a **ContinuedAsNew** run from the list, then
   `temporal workflow query --workflow-id watch-bos-rtr-01 --run-id <that id> --type status`. You
   get that run's final state, frozen. Without `--run-id`, you get the latest.

## Check yourself

1. What happens to a workflow run whose history reaches the limit?
2. What carries over to the new run, and what doesn't?
3. Why is the continue-as-new check placed after the interval wait?
4. Why wait for `all_handlers_finished` first?
5. After a roll-over, how do you see the state an *old* run ended with?

<details>
<summary>Answers</summary>

1. The server terminates it. Long before that, replay gets slow, which is why you continue as
   new well before any limit.
2. The workflow ID and the input you pass to `continue_as_new`. Nothing else: in-memory state,
   history and pending timers are gone.
3. So the new run's first check happens one interval after the last one, not immediately.
4. So a signal or update handler that's partway through finishes before the run ends, instead
   of being cut off.
5. Query it with its run ID: `--run-id` in the CLI, or `get_workflow_handle(id, run_id=...)`.
   A handle without a run ID always goes to the latest run.

</details>

## Solution

[`solutions/day-12/`](../../../solutions/day-12/): carried-state fields on `WatchRequest`;
`__init__` reads them and the loop continues-as-new in `workflows/watch.py`; `start` takes an
interval and max checks in `starters/watch.py`. `tests/test_watch.py` checks that state carries
over, that a pause sent during a roll-over isn't lost, and that the interval and last facts
survive. `tests/histories/watch_can.json` is a real run ending in continue-as-new.
