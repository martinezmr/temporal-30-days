# Day 04 — Determinism, the sandbox, and replay

[← Day 03](../day-03-models-and-failures/README.md) · [Day 05 →](../day-05-heartbeats-and-threads/README.md)

**Time:** 60–90 minutes · **Needs the cEOS lab?** No · **Solution:** [`solutions/day-04/`](../../../solutions/day-04/)

## Why today matters

On Day 1 you killed a worker and the workflow carried on as if nothing happened. Today you learn
*how*, because the mechanism comes with one rule you must never break in workflow code. Break it
and a workflow that's been waiting three days for a maintenance window gets stuck the next time
a worker restarts.

The rule: **workflow code must be deterministic.** Given the same history, it must make the same
decisions every time it runs. Today you'll see why, what breaks it, and how Temporal's Python
sandbox and replay tests catch mistakes before they reach production.

## Concept

### Replay: how a worker picks up where another left off

A worker doesn't save your workflow's variables anywhere. When it needs to continue a workflow
(after a restart, or simply because the workflow hasn't been in its memory for a while), it
**replays**: it runs your `run()` method again from the top, feeding it the event history.

Each time your code reaches something that needs the outside world (`execute_activity`, a timer,
starting a child workflow), it produces a **command**. During replay, Temporal checks each command
against the next matching event in the history:

- **It matches** ("schedule `get_device_facts`" and history says `get_device_facts` was
  scheduled): Temporal doesn't run the activity again. It hands your code the **result recorded in
  history**, and your code moves on.
- **It doesn't match** (your code now asks for `say_hello` where history recorded
  `get_device_facts`): Temporal can't know what to do, so it stops with a **nondeterminism
  error**. The workflow is stuck until you fix the code.

Here's `GetFactsWorkflow` replaying after a worker crash that happened just after the activity
finished:

| Your code reaches | Command it produces | History says | Result |
| --- | --- | --- | --- |
| `await workflow.execute_activity(get_device_facts, ...)` | ScheduleActivityTask `get_device_facts` | Event 5: ActivityTaskScheduled `get_device_facts` | Match. The activity is **not** re-run. |
| (waiting on the `await`) | — | Event 7: ActivityTaskCompleted with the facts | The `await` returns the recorded facts |
| `workflow.logger.info(...)` | — | — | Suppressed during replay, so no duplicate log line |
| `return FactsReport(..., collected_at=workflow.now())` | CompleteWorkflowExecution | (end of history) | New: this is where the crash interrupted. The worker carries on live from here. |

That's why the device isn't asked for `show version` twice. The result was already in history.

### What breaks determinism

Anything that can give a different answer on a later run of the same code:

| Don't do this in a workflow | Why | Do this instead |
| --- | --- | --- |
| `datetime.now()`, `time.time()` | Different every run | `workflow.now()`: the time recorded in history |
| `random.random()`, `uuid.uuid4()` | Different every run | `workflow.random()`, `workflow.uuid4()` |
| Network or file I/O, `pyeapi.connect(...)` | The world changes between runs | Put it in an activity |
| `time.sleep()` | Blocks, and isn't recorded | `await asyncio.sleep()` / `workflow.sleep()` (a durable timer, Day 11) |
| Reading env vars or global mutable state | Could differ on another worker | Pass values in as input |
| Iterating a `set` to decide order | Order isn't guaranteed | Sort first, or use a list |
| **Editing workflow code while workflows are running** (adding, removing or reordering activity calls) | Old histories no longer match the new commands | Versioning, Day 19. For now: let them finish first |

Activities have none of these restrictions. Activities are allowed to be non-deterministic;
that's what they're for. Their *results* are recorded, and replay uses the recorded result.

### The sandbox catches the obvious mistakes

The Python SDK runs workflow code in a **sandbox**. It re-imports your workflow module in an
isolated environment, and blocks known non-deterministic calls. Call `datetime.now()` in a
workflow and you don't get a time. You get:

```
Cannot access datetime.datetime.now.__call__ from inside a workflow.
```

The workflow **task** fails, and Temporal retries the workflow task, so the workflow shows as
**Running** with a `WorkflowTaskFailed` event, not Failed. That's on purpose: it's a bug in your
code, so Temporal waits for you to deploy a fix instead of failing a workflow that might hold
days of state.

This is also why workflow files import activities and models inside
`workflow.unsafe.imports_passed_through()`: it tells the sandbox "this module is safe, share it
instead of re-importing it". Without it, the sandbox would re-import pyeapi and everything it
imports (HTTP clients, sockets), and refuse.

The sandbox can't catch everything: reordering two activity calls is perfectly "legal" Python.
That's what **replay testing** is for.

### `workflow.logger`

Because workflow code re-runs during replay, a `print()` in a workflow prints again every time it
replays. `workflow.logger` knows when it's replaying and stays quiet, so you see each line once.

## Walkthrough

Today's change is small. The lesson is in the reasons behind it.

### 1. `models.py`: a report with a timestamp

```python
# file: netops_temporal/models.py
class FactsReport(BaseModel):
    facts: DeviceFacts
    collected_at: datetime
```

### 2. `workflows/facts.py`: use workflow time and the workflow logger

```python
# file: netops_temporal/workflows/facts.py
    @workflow.run
    async def run(self, req: FactsRequest) -> FactsReport:
        facts = await workflow.execute_activity(
...
        # workflow.logger skips lines while the workflow is replaying, so this logs once.
        workflow.logger.info("%s runs EOS %s", facts.device, facts.version)
        # workflow.now(), not datetime.now(): on replay it returns the same time as the
        # first run, because it comes from the event history.
        return FactsReport(facts=facts, collected_at=workflow.now())
```

`workflow.now()` returns the time of the current workflow task as recorded in history, in UTC.
On the first run it's roughly the real time. On every replay it's *exactly the same* value, so
the decision (and the result) never changes.

### 3. A replay test (in `tests/test_determinism.py`)

You'll write tests properly on Day 6, but this one shows replay so directly that it belongs
today. It runs the real workflow, grabs its history, then replays that history against two
versions of the code:

```python
# file: tests/test_determinism.py
@workflow.defn(name="GetFactsWorkflow")
class ChangedGetFactsWorkflow:
    """GetFactsWorkflow after a careless edit: it now calls another activity first."""

    @workflow.run
    async def run(self, req: FactsRequest) -> FactsReport:
        await workflow.execute_activity(
            "say_hello", req.device, start_to_close_timeout=timedelta(seconds=10)
        )
...
    # The code that produced the history replays cleanly...
    await Replayer(
        workflows=[GetFactsWorkflow], data_converter=pydantic_data_converter
    ).replay_workflow(history)

    # ...but the edited code asks for a different activity than history recorded.
    with pytest.raises(workflow.NondeterminismError):
        await Replayer(
            workflows=[ChangedGetFactsWorkflow], data_converter=pydantic_data_converter
        ).replay_workflow(history)
```

`Replayer` runs workflow code against a saved history **without a server and without running any
activities**. It's the "worker restarts and replays" scenario, as a unit test. The changed class
uses the same workflow name (`name="GetFactsWorkflow"`), so it stands in for "the code after
your edit".

## Run it

Restart the worker, then:

```bash
uv run --env-file .env python -m netops_temporal.starters.facts bos-rtr-01
```

Expected:

```
bos-rtr-01: facts=DeviceFacts(device='bos-rtr-01', model='cEOSLab', version='4.32.0F') collected_at=datetime.datetime(2026, 11, 8, 0, 30, 27, 319648, tzinfo=TzInfo(0))
```

The worker logs `bos-rtr-01 runs EOS 4.32.0F` once. Run the solution's tests, including the
replay test:

```bash
scripts/test-solutions.sh 04
```

Copy `tests/test_determinism.py` from the solution into your own `tests/` if you want it in
your suite (`uv run pytest`).

## Break it

1. **Wall-clock time.** In `workflows/facts.py`, change `collected_at=workflow.now()` to
   `collected_at=datetime.now()` (import `datetime` from `datetime`). Restart the worker and run
   the starter. It hangs. In the UI the workflow is **Running**, and the history has a red
   **WorkflowTaskFailed** event with `Cannot access datetime.datetime.now.__call__ from inside a
   workflow`. The worker log shows the same error, repeating as Temporal retries the task. Revert
   the change and restart the worker: the *same* workflow completes. Nothing was lost; it was
   waiting for fixed code.
2. **Change code under a running workflow.**
   - Make a workflow wait: stop a device (mock: `MOCK_UNREACHABLE=bos-rtr-01`), temporarily set
     `maximum_attempts=50`, restart the worker, and start facts for that device.
   - While it's retrying, add a new activity call *before* `get_device_facts` in the workflow
     (copy the `say_hello` call from the test above). Restart the worker and bring the device back.
   - The workflow doesn't complete. **WorkflowTaskFailed** with a nondeterminism error: the new
     code asks for `say_hello`, history says `get_device_facts`.
   - Revert, restart the worker, and it completes. Day 19 shows how to make changes like this
     safely.
3. **Prove the activity isn't re-run.** Run facts for a device and watch the worker log: one
   `Getting facts from ...` line. Restart the worker and query nothing, start nothing: no new
   line appears, because finished workflows aren't re-run. Then export the history:
   `temporal workflow show --workflow-id facts-bos-rtr-01 -o json > /tmp/h.json`. On Day 6 you'll
   replay files like this in a test, and no device is touched when you do.

## Check yourself

1. Why can activities call `datetime.now()` but workflows can't?
2. During replay, does `get_device_facts` run again? Where does the workflow get its result?
3. A workflow shows **Running** with a `WorkflowTaskFailed` event. Is it lost? What do you do?
4. Name a non-deterministic change the sandbox can't catch, and how you'd catch it.
5. Why use `workflow.logger` instead of `print()` in a workflow?

<details>
<summary>Answers</summary>

1. Activity results are recorded in history, and replay uses the recorded result instead of
   re-running the activity. Workflow code itself re-runs on replay, so anything it computes must
   come out the same every time.
2. No. Replay matches the "schedule activity" command against the recorded event and returns the
   recorded `ActivityTaskCompleted` result.
3. Not lost. The workflow task is retried until it succeeds. Fix the code (or roll back the
   deploy), restart the worker, and it continues from where it was.
4. Adding, removing or reordering activity calls in a workflow that has running executions.
   Replay tests against saved histories catch it (Day 6), and versioning lets you make the change
   safely (Day 19).
5. Workflow code re-runs during replay. `print()` would print again every time;
   `workflow.logger` suppresses output while replaying.

</details>

## Solution

[`solutions/day-04/`](../../../solutions/day-04/): `FactsReport` in `models.py`, the updated
`workflows/facts.py`, and `tests/test_determinism.py` with the replay test.
