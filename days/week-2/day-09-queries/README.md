# Day 09 — Queries: ask a running workflow what it knows

[← Day 08](../day-08-signals/README.md) · [Day 10 →](../day-10-updates/README.md)

**Time:** 60 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-09/`](../../../solutions/day-09/)

## Why today matters

Yesterday's watch runs, and you can pause it. But you can't *see* it. Is it paused? How many
checks has it done? What version did the device report last time? Did the last check fail, and
why? Today the only answer is to dig through event history.

Today you add a **query**: one call that returns the watch's current state as a typed model. You
also fix a real weakness: yesterday, an unreachable device killed the whole watch after 3
attempts. A watch should outlive a device outage. Now it records the error, which the query shows,
and keeps watching.

## Concept

### Queries: read-only, synchronous, not in history

A **query** is a method marked `@workflow.query`. A client calls it by workflow ID and gets its
return value back:

- It runs **on a worker**, against the workflow's state at that moment. If the worker doesn't
  have the workflow in memory, it replays the history first to rebuild the state, then answers.
- It's **read-only**. It must not change state, start activities or wait for anything. It's a
  plain `def`, not `async def`.
- It's **not recorded in history**. Querying a workflow a thousand times adds nothing to it.
- It **needs a worker**. The server can't answer by itself, because the state only exists as
  the result of running your code.

Network analogy: `show` commands. They tell you the device's current state without changing it,
and running them a thousand times doesn't fill the log.

### Signal vs query so far

| | Signal (Day 8) | Query (today) |
| --- | --- | --- |
| Direction | Into the workflow | Out of the workflow |
| Changes state? | Yes | Never |
| Returns a value? | No | Yes |
| In history? | Yes (**WorkflowExecutionSignaled**) | No |
| Works with no worker? | Yes, it's stored and waits | No, it fails |

Tomorrow's **updates** combine the best of both: they change state *and* return a value.

### Errors as state

An activity that fails all its attempts raises `ActivityError` in the workflow. On Day 7 you
caught it to report partial failure as data. The watch does the same thing over time: it catches
the error, stores the message in `self.last_error`, and loops on. The query makes that visible.

## Walkthrough

### 1. `models.py`: what the query returns

```python
# file: netops_temporal/models.py
class WatchStatus(BaseModel):
    """What DeviceWatchWorkflow.status returns: a snapshot of the workflow's state."""

    device: str
    paused: bool
    checks: int
    last_facts: DeviceFacts | None
    last_error: str | None
```

Query results go through the data converter like everything else, so a Pydantic model works
(Day 3).

### 2. `workflows/watch.py`: remember the device and the last error

```python
# file: netops_temporal/workflows/watch.py
        self.last_error: str | None = None
        self.device = ""

    @workflow.run
    async def run(self, req: WatchRequest) -> None:
        self.device = req.device
```

The query has no arguments, so the workflow keeps the device name as state.

```python
# file: netops_temporal/workflows/watch.py
            try:
                self.last_facts = await workflow.execute_activity(
                    get_device_facts,
                    FactsRequest(device=req.device),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                self.checks += 1
                self.last_error = None
            except ActivityError as err:
                # All 3 attempts failed. A watch shouldn't die because the device is down:
                # remember why, and try again at the next interval.
                self.last_error = str(err.cause)
```

- `ActivityError` comes from `temporalio.exceptions`. It's what the workflow sees once Temporal
  has given up on the activity. `err.cause` is the activity's own failure, such as
  `DeviceUnreachableError: bos-rtr-01 is unreachable (MOCK_UNREACHABLE)`.
- A failed check doesn't count in `checks`, and a good check clears `last_error`.

### 3. The query

```python
# file: netops_temporal/workflows/watch.py
    # A query reads state and returns it. It must not change anything, and it isn't
    # recorded in history.
    @workflow.query
    def status(self) -> WatchStatus:
        return WatchStatus(
            device=self.device,
            paused=self.paused,
            checks=self.checks,
            last_facts=self.last_facts,
            last_error=self.last_error,
        )
```

### 4. `starters/watch.py`: a `status` action

```python
# file: netops_temporal/starters/watch.py
    elif action == "status":
        # A query runs on a worker, against the workflow's current state, and returns a value.
        status = await client.get_workflow_handle(workflow_id).query(DeviceWatchWorkflow.status)
        print(status.model_dump_json(indent=2))
```

## Run it

Restart the worker, then:

```bash
uv run --env-file .env python -m netops_temporal.starters.watch bos-acc-01
uv run --env-file .env python -m netops_temporal.starters.watch bos-acc-01 status
```

Expected:

```
started watch-bos-acc-01
{
  "device": "bos-acc-01",
  "paused": false,
  "checks": 1,
  "last_facts": {
    "device": "bos-acc-01",
    "model": "cEOSLab",
    "version": "4.32.0F"
  },
  "last_error": null
}
```

Query it a few more times, then open the workflow's history in the UI: there's no trace of the
queries. The CLI can query too, by the query's name:

```bash
temporal workflow query --workflow-id watch-bos-acc-01 --type status
```

The UI has a **Queries** tab that lists the workflow's queries and runs them for you.

## Break it

1. **Query with no worker.** Stop the worker and run `status`. After about 30 seconds it fails
   with `RPCError: no poller seen for task queue recently, worker may be down`. Unlike a signal,
   a query can't wait in history for a worker to show up. Start the worker again and the query
   answers at once, with the same `checks`: the new worker rebuilt the state by replaying the
   history.
2. **A device outage.** Run the worker with `LAB_MODE=mock MOCK_UNREACHABLE=bos-acc-01`, then
   `check-now` and `status`. A few seconds later (three attempts) the status shows
   `"last_error": "DeviceUnreachableError: bos-acc-01 is unreachable (MOCK_UNREACHABLE)"`, and the
   workflow is still **Running**. Restart the worker without `MOCK_UNREACHABLE`, send `check-now`,
   and `last_error` goes back to `null`.
3. **Query a finished workflow.** `temporal workflow terminate --workflow-id watch-bos-acc-01`,
   then `status` again (worker running). It still answers. The worker replays the closed
   workflow's history to rebuild its final state. That works for as long as the server keeps the
   history (the namespace's retention period).
4. **Change state in a query.** Nothing stops you, which is why it's a trap. Add
   `self.checks += 100` at the top of `status`, restart the worker, and query twice: `checks` goes
   up by 100 each time, as if it worked. Now restart the worker and query again: the extra
   hundreds are gone. Queries aren't in history, so a change made in one is never replayed; it
   only lived in that worker's memory. Put it back.

## Check yourself

1. Why does a query need a running worker, when a signal doesn't?
2. You query a workflow 10,000 times. How much does its history grow?
3. Why does the watch catch `ActivityError` instead of letting it fail the workflow?
4. A new worker starts and immediately answers a query about a 3-week-old workflow. Where did it
   get the state?

<details>
<summary>Answers</summary>

1. The state a query reads only exists as the result of running your workflow code, which only
   a worker can do. A signal just has to be written into history, and the server can do that
   alone.
2. Not at all. Queries aren't recorded.
3. Because a watch is meant to survive outages. Failing the workflow would stop all future
   checks. Recording the error as state keeps it visible (through the query) without ending
   the watch.
4. From the event history. The worker replayed it from the start, which rebuilt every attribute,
   then ran the query on the result.

</details>

## Solution

[`solutions/day-09/`](../../../solutions/day-09/): `WatchStatus` in `models.py`; the `status`
query and `last_error` handling in `workflows/watch.py`; a `status` action in
`starters/watch.py`. `tests/test_watch.py` adds the status query, an unreachable device that
doesn't stop the watch, and a query answered by a brand-new worker that has to replay.
