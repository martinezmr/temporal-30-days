# Day 02 — First real activity: facts over eAPI with pyeapi

[← Day 01](../day-01-lab-up/README.md) · [Day 03 →](../day-03-models-and-failures/README.md)

**Time:** 60–90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-02/`](../../../solutions/day-02/)

## Why today matters

You run a script that pulls `show version` from every device. One router is mid-reboot. A normal
script either crashes or you've written a `for attempt in range(5): try/except/sleep` loop, again,
in every script.

Today you write your first activity that talks to a real device, and let Temporal own the
"try again later" part. When `bos-rtr-01` is down, the workflow doesn't fail. It waits, retries
on a schedule you choose, and carries on the moment the device answers. If it never does, you
get a clear failure telling you exactly what happened on each attempt.

## Concept

### Activities are where the I/O lives, and where retries happen

A workflow decides; an activity does. Anything that touches the outside world (devices, APIs,
files, databases) goes in an activity, because activities are the part Temporal will **retry**.
When an activity raises an exception, Temporal records the failure and, following the activity's
**retry policy**, runs it again later, possibly on another worker. The workflow just sees
`await workflow.execute_activity(...)` take longer.

The workflow itself is *not* retried when an activity fails. It stays exactly where it was,
waiting on that `await`. If the activity eventually gives up (it runs out of attempts), the
`await` raises an `ActivityError` inside the workflow. If the workflow doesn't catch it, the
workflow fails.

### Timeouts: how long is too long?

Every activity call needs at least one timeout. There are four:

| Timeout | Measures | Use it for |
| --- | --- | --- |
| **start-to-close** | One attempt, from when a worker picks it up until it returns | **Always set this.** "A `show version` that hasn't come back in 30 s is stuck." |
| **schedule-to-close** | The whole thing, across all attempts and the waits between them | A hard deadline: "give up on this device after 10 minutes, however many attempts that is" |
| **schedule-to-start** | Time spent waiting in the task queue before a worker picks it up | Detecting "no worker is running this activity" (rarely needed) |
| **heartbeat** | Time between progress pings from a long activity | Long activities. That's Day 5. |

Without start-to-close, a hung SSH session or an HTTP call that never returns would hold an
attempt open forever, and the retry policy would never get a chance to help.

### Retry policies: you choose the schedule

If you don't pass a retry policy, Temporal's default retries **forever**: 1 s, then doubling, up
to 100 s between attempts. That's sometimes what you want (a device that *will* come back), but
for a facts job you'd rather know within a minute. A `RetryPolicy` sets:

- `initial_interval`: wait before the 2nd attempt (2 s here)
- `backoff_coefficient`: multiply the wait each time (2.0 → 2 s, 4 s, 8 s, 16 s)
- `maximum_interval`: cap on the wait (default 100 × initial)
- `maximum_attempts`: total attempts including the first (5 here; 0 means unlimited)

### Sync activities and the thread pool

pyeapi, Netmiko and NAPALM are all **blocking** libraries: when pyeapi waits for a device to
answer, the whole thread waits with it. That matters because a Temporal worker is an `asyncio`
program. If you call a blocking library inside an `async def` activity, you freeze the worker's
event loop: it stops talking to the server, every workflow on that worker stalls, and you get
confusing timeouts that have nothing to do with the device.

The fix is simple: write blocking activities as plain **`def`** functions and give the worker a
thread pool (`activity_executor=ThreadPoolExecutor(...)`). Temporal runs each `def` activity on
a pool thread, so a slow device only ties up its own thread. All the device activities in this
course are `def` activities for this reason.

### About `run_commands`

pyeapi's `Node` object has a method called **`run_commands()`**: give it a list of CLI commands,
and it sends them over eAPI (EOS's JSON-RPC API, the `runCmds` method) and returns one parsed JSON
result per command. We wrap it in our own small function, **`run_show()`**, for two reasons: so
activities don't build connections themselves, and so the same call can return mock data when
`LAB_MODE=mock`. If you've seen `run_commands` elsewhere, that's where it comes from.

## Walkthrough

Four new files, plus two changes to the worker.

### 1. `devices/eapi.py`: talk to a device

```python
# file: netops_temporal/devices/eapi.py
import pyeapi

from netops_temporal.constants import DEVICE_PASSWORD, DEVICE_USERNAME, device_address, lab_mode
from netops_temporal.mock import devices as mock_devices


def run_show(device: str, commands: list[str]) -> list[dict]:
    """Run show commands on one device; returns one JSON result dict per command."""
    if lab_mode() == "mock":
        return mock_devices.show(device, commands)

    address = device_address(device)
    node = pyeapi.connect(
        transport="https",
        host=address.host,
        port=address.eapi_port,
        username=DEVICE_USERNAME,
        password=DEVICE_PASSWORD,
        timeout=10,
        return_node=True,
    )
    return node.run_commands(commands)
```

- `device_address(device)` comes from Day 1's `constants.py`: the host and port from
  `DEVICE_HOSTS`. Through `lab/tunnels.sh` that's `127.0.0.1` and a local port; on a routed lab
  it's the management IP and 443.
- `pyeapi.connect(..., return_node=True)` returns a `Node`, pyeapi's handle for one device.
  It doesn't connect yet; the HTTPS request happens in `run_commands`.
- `timeout=10` is pyeapi's own socket timeout, so a dead device fails in 10 s instead of hanging.
  It sits comfortably inside the activity's 30 s start-to-close timeout.
- `node.run_commands(["show version"])` returns `[{"modelName": "cEOSLab", "version": ..., ...}]`.
  pyeapi quietly prepends `enable` and strips its result for you.

### 2. `activities/facts.py`: the activity

```python
# file: netops_temporal/activities/facts.py
from temporalio import activity

from netops_temporal.devices.eapi import run_show


# A plain `def`, not `async def`: pyeapi blocks while it waits for the device, so this
# activity runs on the worker's thread pool instead of its event loop.
@activity.defn
def get_device_facts(device: str) -> dict:
    activity.logger.info("Getting facts from %s", device)
    [version] = run_show(device, ["show version"])
    return {
        "device": device,
        "model": version["modelName"],
        # EOS reports e.g. "4.32.0F-36401836.4320F (engineering build)"; keep the release.
        "version": version["version"].split("-")[0],
    }
```

Notice what's *not* here: no `try/except`, no retry loop, no sleep. If the device is down,
`run_show` raises, the activity attempt fails, and Temporal schedules the next attempt. The return
value must be something Temporal can serialize to JSON; a `dict` of strings is fine today, and
Day 3 replaces it with a typed model.

### 3. `workflows/facts.py`: the workflow and its policies

```python
# file: netops_temporal/workflows/facts.py
@workflow.defn
class GetFactsWorkflow:
    @workflow.run
    async def run(self, device: str) -> dict:
        return await workflow.execute_activity(
            get_device_facts,
            device,
            # One attempt may take at most 30 s before Temporal gives up on it and retries.
            start_to_close_timeout=timedelta(seconds=30),
            # Wait 2 s, 4 s, 8 s, 16 s between attempts, and stop after the 5th.
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=5,
            ),
        )
```

The timeouts and retry policy are set **by the caller (the workflow)**, not on the activity
itself. The same activity can be called patiently by one workflow and impatiently by another.
`RetryPolicy` is imported from `temporalio.common`, and the activity is imported with
`imports_passed_through()` as on Day 1.

### 4. `workers/main.py`: register it, and add the thread pool

```python
# file: netops_temporal/workers/main.py
    # Sync (`def`) activities run on this thread pool: up to 10 at once. The worker must not
    # accept more activities than that (the SDK default is 100), or the extras wait inside
    # the worker with their timeouts already running.
    with ThreadPoolExecutor(max_workers=10) as executor:
        worker = Worker(
            client,
            task_queue=ORCHESTRATION_TASK_QUEUE,
            workflows=[HelloWorkflow, GetFactsWorkflow],
            activities=[say_hello, get_device_facts],
            activity_executor=executor,
            max_concurrent_activities=10,
        )
```

Without `activity_executor`, the worker refuses to start and tells you a sync activity needs one.

Two numbers, and they must match:

- `max_workers=10` is the thread pool: how many `def` activities can *run* at once.
- `max_concurrent_activities=10` is the worker's **activity slots**: how many activity tasks it
  *accepts* from the server at once. The default is 100.

With 10 threads and 100 slots, the worker would accept 100 activities and run 10. The other 90
would wait inside the worker, with their start-to-close timeouts already counting, instead of
waiting in the task queue where another worker could pick them up. Matching the two means the
11th activity stays in the task queue until a thread is free. Day 7 shows why that number matters.

### 5. `starters/facts.py`: one workflow per device

```python
# file: netops_temporal/starters/facts.py
    results = await asyncio.gather(
        *(
            client.execute_workflow(
                GetFactsWorkflow.run,
                device,
                id=f"facts-{device}",
                task_queue=ORCHESTRATION_TASK_QUEUE,
            )
            for device in devices
        ),
        return_exceptions=True,
    )
```

`asyncio.gather` starts all the workflows at once and waits for them all. `return_exceptions=True`
means one failed device doesn't hide the others' results; its failure is printed instead.

## Run it

Worker in terminal 1 (restart it whenever you change code):

```bash
uv run --env-file .env python -m netops_temporal.workers.main
```

Starter in terminal 2:

```bash
uv run --env-file .env python -m netops_temporal.starters.facts
```

Expected:

```
bos-rtr-01: {'device': 'bos-rtr-01', 'model': 'cEOSLab', 'version': '4.32.0F'}
bos-acc-01: {'device': 'bos-acc-01', 'model': 'cEOSLab', 'version': '4.32.0F'}
nyc-rtr-01: {'device': 'nyc-rtr-01', 'model': 'cEOSLab', 'version': '4.32.0F'}
nyc-acc-01: {'device': 'nyc-acc-01', 'model': 'cEOSLab', 'version': '4.32.0F'}
```

No lab? Put `LAB_MODE=mock` in `.env` (or prefix both commands with `LAB_MODE=mock`) and you'll
get the same output from recorded data.

In the UI, open `facts-bos-rtr-01`. The history looks like Day 1's, but the activity is now
`get_device_facts`. Click **ActivityTaskStarted** and note `attempt: 1`.

## Break it

1. **Take a device away.**
   - Live lab: `docker stop bos-rtr-01` on the lab VM (or stop `lab/tunnels.sh`).
   - Mock: set `MOCK_UNREACHABLE=bos-rtr-01` in `.env` and restart the worker.

   Then run `... starters.facts bos-rtr-01`. In the UI, open the workflow and look at
   **Pending Activities**: the attempt count climbs (2, 3, 4...), **Last Failure** shows the error, and
   **Next Retry** counts down 2 s, 4 s, 8 s. What the error says depends on how you reach the
   lab: through `lab/tunnels.sh` with the tunnel stopped, pyeapi says
   `Socket error during eAPI connection: [Errno 61] Connection refused` at once; on a routed lab
   with the container stopped, each attempt waits for pyeapi's 10 s timeout first. The worker logs one line per attempt, each tagged
   with its `attempt` number.
2. **Bring it back before attempt 5** (`docker start bos-rtr-01`, restart the tunnels, or clear
   `MOCK_UNREACHABLE` and restart the worker). The next attempt succeeds and the starter prints
   the facts. No code change, no rerun. The workflow was waiting all along.
3. **Let it run out.** Take the device away again and wait: about 30 s of backoff, plus up to
   10 s per attempt if each one times out (so up to ~80 s on a routed lab). The starter prints a
   `WorkflowFailureError`. In the UI the workflow is **Failed**; expand the failure: the
   workflow failed *because* an `ActivityError` (after 5 attempts) was caused by the pyeapi
   connection error. That chain (workflow ← activity ← root cause) is how every Temporal failure
   reads.
4. **Freeze the event loop (optional, instructive).** Change `def get_device_facts` to
   `async def get_device_facts` and restart the worker. Nothing warns you; the blocking pyeapi
   call now simply runs on the event loop. Make one device slow or dead and start facts for all
   four: every workflow on that worker stalls while that one call waits, not just that device's.
   Change it back.

## Check yourself

1. In Break it #3, what failed first: the activity or the workflow? What would have happened to
   the workflow if it had caught the exception?
2. Why is `get_device_facts` a `def` and not an `async def`?
3. Which timeout limits one attempt? Which would you add to say "give up on this device after
   two minutes, whatever happens"?
4. With this retry policy, about how long after the first failure is the 5th attempt?
5. Where do the retry settings live: on the activity or on the workflow's call to it? Why does
   that matter?

<details>
<summary>Answers</summary>

1. The activity failed 5 times, then Temporal stopped retrying and raised `ActivityError` in the
   workflow at the `await`. The workflow didn't catch it, so it failed too. If it had wrapped the
   call in `try/except ActivityError`, it could have recorded "bos-rtr-01 unreachable" and
   completed successfully. Day 7 does exactly that.
2. pyeapi blocks the thread while waiting on the device. In an `async def` activity that would
   block the worker's event loop and stall every workflow on the worker. A `def` activity runs on
   the thread pool instead.
3. start-to-close limits one attempt. schedule-to-close (`schedule_to_close_timeout=timedelta(minutes=2)`)
   caps the total time across all attempts and waits.
4. 2 + 4 + 8 + 16 = 30 s of waiting, plus the time each failed attempt took.
5. On the call (`execute_activity` options). Different workflows can call the same activity with
   different patience.

</details>

## Solution

[`solutions/day-02/`](../../../solutions/day-02/): `devices/eapi.py`, `activities/facts.py`,
`workflows/facts.py`, `starters/facts.py`, the updated `workers/main.py`, and
`tests/test_facts.py` (you'll learn to write tests like it on Day 6). Compare with your code:

```bash
diff -r -x __pycache__ src/netops_temporal solutions/day-02/netops_temporal
```
