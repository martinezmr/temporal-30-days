# Day 05 — Netmiko, blocking libraries, heartbeats, and cancellation

[← Day 04](../day-04-determinism/README.md) · [Day 06 →](../day-06-testing/README.md)

**Time:** 60–90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-05/`](../../../solutions/day-05/)

## Why today matters

TAC wants a dozen `show` outputs from a router. Collecting them over SSH takes minutes on a busy
box. Halfway through, the worker restarts (a deploy, a laptop lid, an OOM kill). Two questions:

1. How does Temporal tell a slow-but-working activity from a dead one, without waiting for a
   ten-minute timeout?
2. When it retries, does it start over at command 1, or pick up where it left off?

Today's answers are **heartbeats**. You'll also make the collection **cancellable**: an operator
can stop it from the UI, and it cleans up instead of being cut off mid-command.

## Concept

### Why Netmiko today

Netmiko logs in over SSH like a person would: it sends a command and reads the screen until the
prompt comes back. It's the library you reach for when there's no API, and it is slow and
**blocking**. Like Day 2's pyeapi activity, it goes in a plain `def` activity on the worker's
thread pool. One Netmiko session ties up one thread for its whole duration, so the pool size
(`max_workers=10`, matched by `max_concurrent_activities=10`) is also "at most 10 SSH sessions
from this worker".

### Heartbeats: "I'm alive, and here's how far I got"

A long activity calls `activity.heartbeat(details)` regularly. Each heartbeat does two jobs:

1. **Liveness.** If no heartbeat arrives within `heartbeat_timeout`, Temporal declares the attempt
   dead and schedules a retry. With a 15 s heartbeat timeout, a crashed worker is noticed in about
   15 s, not when the 10-minute start-to-close timeout expires.
2. **Progress.** The `details` you pass are stored on the server. The *next* attempt reads them
   from `activity.info().heartbeat_details` and can skip work that's already done.

So there are two timeouts working together:

| Timeout | Here | Question it answers |
| --- | --- | --- |
| `start_to_close_timeout` | 10 min | "Is this attempt taking unreasonably long overall?" |
| `heartbeat_timeout` | 15 s | "Has this attempt gone silent?" |

### Heartbeats are throttled, so make each step safe to repeat

The SDK doesn't send every heartbeat to the server. It sends the first one immediately, then at
most one about every **80% of `heartbeat_timeout`** (12 s here), always with the latest
details. If the worker dies, the server only has the last heartbeat it *received*.

In this course's own test run, the worker was killed after finishing 4 commands, and the retry
resumed at command 2: heartbeats 2–4 hadn't been sent yet. So **resume means "from at least the
last recorded checkpoint", never "from exactly where it stopped"**. Design each step so doing it
twice is harmless. Here, re-running a `show` command and overwriting its file is fine. A config
push step would need more care (Day 17).

### Cancellation arrives through heartbeats

When someone cancels a workflow, Temporal asks its running activities to cancel. The request
reaches an activity **in the response to a heartbeat**. An activity that never heartbeats never
hears it, and runs to the end. In a sync (`def`) activity, the SDK delivers it by raising
`temporalio.exceptions.CancelledError` inside the activity's thread. Catch it to clean up, then
**re-raise** so Temporal knows the activity honored the cancel.

Because of throttling, cancellation can take up to one throttle interval (~12 s here) to arrive.

By default a workflow doesn't wait for the activity to finish cleaning up. Setting
`cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED` on the call makes the
workflow wait until the activity has actually stopped, so "workflow canceled" really means
"nothing is still talking to the device".

### Keep big outputs out of history

Everything an activity returns is stored in the workflow's history, and histories have size
limits (a few MB per payload, ~50 MB total). Ten `show` outputs, or a full config, don't belong
there. The activity writes outputs to files under `OUTPUT_DIR` and returns **where** they are. A
good rule: return identifiers and summaries, not blobs.

## Walkthrough

### 1. `devices/ssh.py`: one SSH session as a context manager

```python
# file: netops_temporal/devices/ssh.py
@contextmanager
def cli_session(device: str) -> Iterator[Callable[[str], str]]:
    """Open one SSH session and yield a `send(command) -> output` function.

        with cli_session("bos-rtr-01") as send:
            print(send("show version"))
    """
    if lab_mode() == "mock":
        yield lambda command: mock_devices.cli(device, command)
        return

    address = device_address(device)
    try:
        conn = ConnectHandler(
            device_type="arista_eos",
            host=address.host,
            port=address.ssh_port,
            username=DEVICE_USERNAME,
            password=DEVICE_PASSWORD,
            conn_timeout=10,
        )
    except NetmikoAuthenticationException as err:
        raise DeviceAuthError(f"{device}: {err}") from err
    except (NetmikoTimeoutException, OSError) as err:
        raise DeviceUnreachableError(f"{device}: {err}") from err
    try:
        conn.enable()
        yield lambda command: conn.send_command(command, read_timeout=60)
    finally:
        conn.disconnect()
```

- One session for all ten commands: logging in ten times would be slower and noisier in the
  device's AAA logs.
- `port=address.ssh_port` is `22`, or the local port `lab/tunnels.sh` forwarded.
- Netmiko's exceptions are translated into our three error types, exactly as Day 3 did for pyeapi.
- `finally: conn.disconnect()` runs on success, on error, *and* on cancellation, so no session is
  left hanging on the device.

### 2. `models.py`: a request and a small result

```python
# file: netops_temporal/models.py
class ShowTechRequest(BaseModel):
    device: str


class ShowTechResult(BaseModel):
    """Where the outputs were written. The outputs themselves stay out of workflow history."""

    device: str
    output_dir: str
    commands_collected: int
    resumed_from: int
```

### 3. `activities/show_tech.py`: heartbeat, resume, clean up

```python
# file: netops_temporal/activities/show_tech.py
@activity.defn
def collect_show_tech(req: ShowTechRequest) -> ShowTechResult:
    # If an earlier attempt died part-way, its last heartbeat says how many commands it finished.
    details = activity.info().heartbeat_details
    start = details[0] if details else 0
    if start:
        activity.logger.info("Resuming %s show tech at command %d", req.device, start + 1)

    out_dir = OUTPUT_DIR / "show-tech" / req.device
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with cli_session(req.device) as send:
            for number, command in enumerate(SHOW_TECH_COMMANDS[start:], start=start + 1):
                (out_dir / f"{number:02d}.txt").write_text(send(command))
                # "I'm alive, and I've finished `number` commands." The server's reply to a
                # heartbeat is also how a cancel request arrives; the SDK then raises
                # CancelledError in this thread, wherever it happens to be.
                activity.heartbeat(number)
    except CancelledError:
        activity.logger.warning("%s show tech cancelled; partial output in %s", req.device, out_dir)
        raise
```

- `heartbeat_details` is a list of whatever the last recorded heartbeat passed: `[4]` means
  "4 commands done". On a first attempt it's empty, so `start` is 0.
- `SHOW_TECH_COMMANDS` is the list of 10 commands in `constants.py` (from Day 1).
- Heartbeat **after** each command is written, so the checkpoint never claims work that isn't on
  disk.
- `except CancelledError: ... raise`: log (or delete partial files, release a lock), then let it
  propagate. Swallowing it would make Temporal think the activity finished normally.
- The rest of the function (not shown) maps `DeviceAuthError` and `UnknownDeviceError` to
  non-retryable `ApplicationError`s, as on Day 3, and returns a `ShowTechResult`.

### 4. `workflows/show_tech.py`: the two timeouts and the cancellation type

```python
# file: netops_temporal/workflows/show_tech.py
@workflow.defn
class ShowTechWorkflow:
    @workflow.run
    async def run(self, req: ShowTechRequest) -> ShowTechResult:
        return await workflow.execute_activity(
            collect_show_tech,
            req,
            # The whole collection may take a while...
            start_to_close_timeout=timedelta(minutes=10),
            # ...but if 15 s pass without a heartbeat, this attempt is presumed dead.
            heartbeat_timeout=timedelta(seconds=15),
            retry_policy=RetryPolicy(maximum_attempts=3),
            # On cancel, wait for the activity to clean up before the workflow finishes.
            cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
```

Rule of thumb: `heartbeat_timeout` must be comfortably longer than your longest single step
(one `show` command), or a slow-but-healthy step looks like a crash.

### 5. Register and start it

Add `ShowTechWorkflow` and `collect_show_tech` to the worker's lists:

```python
# file: netops_temporal/workers/main.py
            workflows=[HelloWorkflow, GetFactsWorkflow, ShowTechWorkflow],
            activities=[say_hello, get_device_facts, collect_show_tech],
```

`starters/show_tech.py` runs one `ShowTechWorkflow` with the ID `show-tech-<device>` and prints
the result.

## Run it

Restart the worker, then:

```bash
uv run --env-file .env python -m netops_temporal.starters.show_tech bos-rtr-01
```

Expected (live, about 2–3 seconds through a tunnel):

```
device='bos-rtr-01' output_dir='output/show-tech/bos-rtr-01' commands_collected=10 resumed_from=0
```

`ls output/show-tech/bos-rtr-01/` shows `01.txt` … `10.txt`. In the UI, open the workflow while
it runs (use the slow mock below to have time) and look at **Pending Activities → Heartbeat
Details** ticking up.

To slow it down enough to watch and break, use mock mode with a delay:

```bash
LAB_MODE=mock MOCK_CLI_DELAY=3 uv run --env-file .env python -m netops_temporal.workers.main
```

## Break it

1. **Kill the worker mid-collection.** With the slow worker running, start show tech for
   `nyc-rtr-01`. After ~13 s (about 4 commands), kill the worker hard (`kill -9`, or close the
   terminal). Watch the UI:
   - The pending activity stays **Running** for a few more seconds, then the attempt fails with
     **Heartbeat timeout**, and attempt 2 is scheduled. Why not a full 15 s? The clock started at
     the last heartbeat the server *received* (about 3 s in, thanks to throttling), not at the
     kill.
   - Start the worker again. Its log says `Resuming nyc-rtr-01 show tech at command 2` (or
     similar), and the final result shows `resumed_from=1`. Not command 1, but not command 5
     either. That's throttling: only the first heartbeat had reached the server. Re-read the
     *throttled* section above, and notice the overwritten files did no harm.
2. **Cancel it.** Start show tech for `nyc-acc-01` with the slow worker, then after a few seconds:
   `temporal workflow cancel --workflow-id show-tech-nyc-acc-01` (or **Request Cancellation** in
   the UI).
   - Within a heartbeat interval, the worker logs
     `nyc-acc-01 show tech cancelled; partial output in output/show-tech/nyc-acc-01`.
   - History shows **ActivityTaskCancelRequested**, then **ActivityTaskCanceled**, then
     **WorkflowExecutionCanceled**. Status: **Canceled**.
   - `ls output/show-tech/nyc-acc-01` shows only some of the files.
   - The starter raises `WorkflowFailureError` whose cause is a `CancelledError`. Callers see a
     cancel as a kind of failure.
3. **Heartbeat timeout too short.** Set `heartbeat_timeout=timedelta(seconds=2)` and run with
   `MOCK_CLI_DELAY=3`. Every attempt times out on its first command, because one step takes longer
   than the heartbeat timeout. After 3 attempts the workflow fails. Put it back to 15 s.
4. **Cancel, then kill.** Cancel a slow run and immediately kill the worker. The cancel never
   reaches the activity, and the attempt dies by heartbeat timeout. Because the workflow is
   waiting for the cancellation to complete, it stays open until you **restart the worker**; then,
   since cancellation was requested, Temporal doesn't retry the activity, and the workflow ends
   **Failed** with "activity Heartbeat timeout". Cancellation is a request, not a guarantee.

## Check yourself

1. For each activity you have so far, is it async or sync, and why?
2. What happens to heartbeats if the worker process dies? How soon does Temporal notice?
3. Your activity heartbeated 4, 5, 6, then the worker died. Why might the retry start at 2?
4. Why does the activity return a directory path instead of the outputs?
5. What must the `except CancelledError` block do last, and why?
6. What does `WAIT_CANCELLATION_COMPLETED` change?

<details>
<summary>Answers</summary>

1. `say_hello` is async (no I/O, can't block). `get_device_facts` and `collect_show_tech` are sync,
   because pyeapi and Netmiko block. They run on the thread pool.
2. They stop. After `heartbeat_timeout` (15 s here) with no heartbeat, the server fails the attempt
   with a heartbeat timeout and schedules a retry.
3. Heartbeats are throttled to about one per 80% of the heartbeat timeout. The last one the server
   *received* may be older than the last one the activity *called*.
4. Activity results are stored in workflow history, which has size limits and is kept for the
   workflow's lifetime. Big outputs go to files; history holds the path.
5. Re-raise. Otherwise Temporal sees a normal return, and the workflow can't tell the work was
   cut short.
6. The workflow waits for the activity to acknowledge the cancel (finish its cleanup) before the
   workflow itself becomes Canceled. Without it, the workflow can finish while the activity is
   still running.

</details>

## Solution

[`solutions/day-05/`](../../../solutions/day-05/): `devices/ssh.py`, `activities/show_tech.py`,
`workflows/show_tech.py`, `starters/show_tech.py`, new models, the updated worker, and
`tests/test_show_tech.py`. The tests drive the activity with `ActivityEnvironment`: they fake a
previous attempt's heartbeat (`heartbeat_details=[4]`) and cancel after the 3rd heartbeat.
