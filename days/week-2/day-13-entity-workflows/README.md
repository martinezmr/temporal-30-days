# Day 13 — Entity workflows: one owner per device

[← Day 12](../day-12-continue-as-new/README.md) · [Day 14 →](../day-14-orchestrator-v0/README.md)

**Time:** 90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-13/`](../../../solutions/day-13/)

## Why today matters

Three people (or three automations) touch `nyc-rtr-01` at the same moment: a backup job, someone
collecting facts, and a compliance check. Each logs in, each runs its commands, and they trample
each other. Sessions pile up, AAA gets hammered, and two jobs write the same output file. The usual
fix is a lock file or a "device busy" flag in a database, plus a lot of hope.

Temporal gives you a cleaner pattern: the **entity workflow**. Each device gets one long-lived
workflow with a fixed ID (`device-nyc-rtr-01`), and every operation on that device is a request
*to that workflow*. The workflow runs them one at a time and keeps a record. Today you build
`DeviceEntityWorkflow` from the pieces of the last five days: updates, update-with-start, an
async handler with a lock, a query, and continue-as-new.

## Concept

### An entity is a workflow per *thing*

So far, workflows have been per *job*: "get facts", "back up everything". An entity workflow is
per *thing*: one for each device, living as long as the device does. Its workflow ID is the
thing's name, which makes it easy to find, and Temporal guarantees there's only ever one running
workflow per ID.

Network analogy: the change manager for one box. Every request for that device goes through them,
they handle one at a time, and they remember what was done.

### Async update handlers do the work

On Day 10 the update handler only changed state. A handler can also be `async` and `await`
activities. That's how the entity works: `submit(op)` runs the operation's activity and returns its
result to the caller, who waits for it like any update.

This means several handlers can be running at once. If three people submit at the same moment,
three `submit` calls are in flight inside one workflow.

### A lock makes them take turns

`asyncio.Lock` works inside a workflow: Temporal runs workflow code on its own deterministic event
loop, so a lock behaves the same on every replay. `async with self.lock:` around the operation
means only one handler talks to the device at a time; the others wait their turn, in order. Without
it, all three activities would be scheduled at once. (In **Break it** you'll see what that does to
the backup files.)

### The run method just waits

The entity's `run` has almost nothing to do: it waits until it's time to continue-as-new (Day
12), lets running handlers finish, and hands over. The work happens in `submit`.

## Walkthrough

### 1. `models.py`

```python
# file: netops_temporal/models.py
class OperationRequest(BaseModel):
    """One thing someone wants done on a device, submitted to its DeviceEntityWorkflow."""

    kind: Literal["facts", "backup"]
    requested_by: str
```

```python
# file: netops_temporal/models.py
class DeviceEntityInput(BaseModel):
    device: str
    max_ops_per_run: int = 200
    # Handed over by continue-as-new, so the `recent` query survives roll-overs.
    recent: list[OperationResult] = Field(default_factory=list)
```

`Literal["facts", "backup"]` means Pydantic rejects any other kind before it reaches the workflow.
`OperationResult` has `kind`, `requested_by`, `ok` and `detail`.

### 2. `workflows/device_entity.py`: state, and a run that waits

```python
# file: netops_temporal/workflows/device_entity.py
    @workflow.init
    def __init__(self, inp: DeviceEntityInput) -> None:
        self.device = inp.device
        self.recent: list[OperationResult] = list(inp.recent)
        self.ops_this_run = 0
        # asyncio.Lock is safe in a workflow: Temporal runs workflow code on its own
        # deterministic event loop. Holding it means "I'm the one talking to this device".
        self.lock = asyncio.Lock()

    @workflow.run
    async def run(self, inp: DeviceEntityInput) -> None:
        # The entity does nothing on its own. It waits; the work happens in `submit`.
        await workflow.wait_condition(
            lambda: (
                self.ops_this_run >= inp.max_ops_per_run
                or workflow.info().is_continue_as_new_suggested()
            )
        )
        # Day 12's rules: let queued operations finish, then hand over to a fresh run.
        await workflow.wait_condition(workflow.all_handlers_finished)
```

### 3. The update: one operation at a time

```python
# file: netops_temporal/workflows/device_entity.py
    # An async update handler can await activities. Several can be in flight at once, so the
    # lock makes them take turns: operations on one device never overlap.
    @workflow.update
    async def submit(self, op: OperationRequest) -> OperationResult:
        async with self.lock:
            try:
                detail = await self._run_operation(op)
                result = OperationResult(
                    kind=op.kind, requested_by=op.requested_by, ok=True, detail=detail
                )
            except ActivityError as err:
                result = OperationResult(
                    kind=op.kind, requested_by=op.requested_by, ok=False, detail=str(err.cause)
                )
            self.recent.append(result)
            self.ops_this_run += 1
            return result

    @submit.validator
    def validate_submit(self, op: OperationRequest) -> None:
        if not op.requested_by.strip():
            raise ValueError("requested_by is required")
```

- A failed operation is a **result** (`ok=False`), not an exception: the caller learns what went
  wrong, and the entity keeps running for the next request.
- The validator insists on a name, so the `recent` record always says who asked.

`_run_operation` picks the activity by `kind`: Day 3's `get_device_facts`, or Day 7's
`backup_running_config`. The backup's file name needs care:

```python
# file: netops_temporal/workflows/device_entity.py
        # Microseconds: operations queued in the same second still get their own file.
        timestamp = workflow.now().strftime("%Y%m%dT%H%M%S%fZ")
```

(The course's first version used whole seconds, and five backups queued together overwrote each
other's files. The test now checks for that.)

### 4. `starters/device_ops.py`: update-with-start

```python
# file: netops_temporal/starters/device_ops.py
async def submit(client: Client, device: str, op: OperationRequest) -> OperationResult:
    # Update-with-start (Day 10): the first operation on a device creates its entity.
    start_op = WithStartWorkflowOperation(
        DeviceEntityWorkflow.run,
        DeviceEntityInput(device=device),
        id=f"device-{device}",
        task_queue=ORCHESTRATION_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
```

Nobody has to create the entities first. The first operation on a device creates its entity, and
every later one finds it. An optional count submits the same operation several times at the same
moment.

## Run it

Restart the worker (`DeviceEntityWorkflow` is registered), then submit five backups at once:

```bash
uv run --env-file .env python -m netops_temporal.starters.device_ops nyc-rtr-01 backup bob 5
uv run --env-file .env python -m netops_temporal.starters.device_ops nyc-rtr-01 facts alice
uv run --env-file .env python -m netops_temporal.starters.device_ops nyc-rtr-01 recent
```

Expected: five `ok=True` backups, each with its own file name, then the facts:

```
kind='backup' requested_by='bob' ok=True detail='output/backups/nyc-rtr-01/20261108T164416633181Z.cfg'
...
kind='facts' requested_by='alice' ok=True detail='EOS 4.32.0F on cEOSLab'
```

Open `device-nyc-rtr-01` in the UI and switch to the **Timeline** view: the five updates were all
accepted at once, but the activity bars sit end to end, never overlapping. In the history, each
**ActivityTaskScheduled** comes after the previous **ActivityTaskCompleted**.

## Break it

1. **Remove the lock.** Replace `async with self.lock:` with `if True:` and run the tests:
   `test_operations_on_same_device_serialize` fails. Both queued backups started in the same
   instant and got the **same** file name, so one overwrote the other. On a real device, that's
   two sessions at once. Put the lock back.
2. **Submit without a name.** `... device_ops nyc-rtr-01 facts " "` fails with
   `WorkflowUpdateFailedError`. The validator rejected it, and the entity's history shows no trace
   of it.
3. **A failing operation.** Run the worker with `LAB_MODE=mock MOCK_AUTH_FAIL=1` and submit
   `facts`. You get `ok=False detail='auth failed for nyc-rtr-01'` back, and the entity is still
   **Running**, ready for the next request.
4. **Roll it over while work is queued.** `test_entity_handlers_finish_before_can` starts an
   entity with `max_ops_per_run=1` and submits two operations at once. The first one completes and
   the run wants to continue-as-new, but the second is still waiting for the lock. Because `run`
   waits for `all_handlers_finished`, both callers get `ok=True`, and the new run's `recent` lists
   both. Delete that `wait_condition` line and run the test to see it fail.

## Check yourself

1. Why does an entity workflow use the device name as its workflow ID?
2. Why is `asyncio.Lock` safe inside a workflow, when normal threading locks aren't?
3. Why does `submit` return `ok=False` instead of raising when the activity fails?
4. Who creates a device's entity workflow?
5. What would happen to queued operations if the entity continued-as-new without waiting for
   `all_handlers_finished`?

<details>
<summary>Answers</summary>

1. So everyone can find it without looking it up, and because Temporal allows only one running
   workflow per ID: that's what makes it the single owner.
2. Workflow code runs on Temporal's deterministic event loop, one step at a time, so the lock is
   acquired in the same order on every replay. A threading lock depends on real thread timing.
3. A failed operation is a normal outcome the caller should see. Raising would fail the update,
   and the record of the attempt would be lost from `recent`.
4. Whoever submits the first operation, through update-with-start. No separate setup step.
5. They'd be cut off when the run ended, and their callers would get errors instead of results.

</details>

## Solution

[`solutions/day-13/`](../../../solutions/day-13/): new `workflows/device_entity.py` and
`starters/device_ops.py`; `OperationRequest`, `OperationResult` and `DeviceEntityInput` in
`models.py`. `tests/test_device_entity.py` checks the result, serialization (activities never
overlap, distinct files), failures as results, the validator, the `recent` query,
update-with-start creating one entity, and queued handlers finishing before continue-as-new.
