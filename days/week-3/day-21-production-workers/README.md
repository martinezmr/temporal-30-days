# Day 21 — Production-shaped workers, on your laptop

[← Day 20](../day-20-observability/README.md) · [Week 4 →](../../week-4/README.md)

**Time:** 90–120 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-21/`](../../../solutions/day-21/)

## Why today matters

Until now, one worker process has done everything: run workflow code, log in to devices, call
Nautobot. That's right for learning, and wrong for the day your automation runs 24/7 against the
production network:

- You can't scale device work without also scaling workflow workers, and you can't restart one
  without the other.
- Nothing stops ten workers from opening forty SSH sessions in the same second, and TACACS
  notices.
- Restarting a worker in the middle of a show tech kills it halfway.
- Every workflow input and result (device names, config lines, backups' paths) sits in plain text
  on the Temporal server, readable by anyone who can open the UI.

Today you fix all four, still entirely on your laptop, and finish with the device worker in a
container.

## Concept

### Split workers by job

| Worker | Task queue | Runs | Needs |
| --- | --- | --- | --- |
| `workers/orchestration.py` | `netops-orchestration` | Workflows only | Temporal, nothing else. No device credentials. Little CPU. |
| `workers/device_io.py` | `netops-device-io` | Activities only | Device credentials, Nautobot token, network reach to the devices |

A workflow says which queue its activities go to (`task_queue=DEVICE_IO_TASK_QUEUE` on every
`execute_activity`). The orchestration worker never runs an activity; if no device-io worker is
running, activities simply **wait** on their queue (no failures, no retries used up), and run as
soon as one starts.

Then each side scales and restarts on its own. And the credentials live only where they're
needed.

Changing an activity's task queue doesn't change replay: the committed histories in
`tests/histories/` still replay. (The task queue isn't part of what replay compares.)

`workers/main.py` stays as the all-in-one **development** worker: it polls both queues in one
process, so day to day you still need one terminal.

### Be gentle with devices

Two limits, at two levels:

| Setting | Scope | Here |
| --- | --- | --- |
| `max_concurrent_activities` | One worker process | 10, matched to its thread pool (Day 7) |
| `max_task_queue_activities_per_second` | **All** workers on the queue, enforced by the server | 5 per second |

The first protects the worker. The second protects the network: start three device-io workers
and the server still hands out no more than 5 activities a second between them. AAA servers and
control-plane CPUs see a steady trickle, not a burst.

### Graceful shutdown

Stopping a process (Ctrl-C, `podman stop`, a deploy, systemd) sends it a signal. The device-io
worker catches SIGTERM and SIGINT and calls `worker.shutdown()`, which:

1. stops polling for new activities,
2. lets running activities finish, for up to `graceful_shutdown_timeout` (30 s here),
3. then cancels whatever is still running (an activity that heartbeats sees the cancellation,
   Day 5), and exits.

A show tech that's in progress finishes instead of being cut off. One that takes longer than 30 s
is cancelled, and its heartbeat lets the next worker resume where it stopped (Day 5).

One catch: whatever sends the signal must wait long enough. `podman stop` waits **10 s** by
default before it kills the process outright, so use `podman stop -t 40`. (In Kubernetes, it's
`terminationGracePeriodSeconds`.)

### Keep payloads off the server with a codec

Everything a workflow receives or returns is a **payload**, stored in history on the server for as
long as history is kept. A **payload codec** runs in your process (worker and starter), and
transforms payloads on the way out and back in. `EncryptionCodec` encrypts them with AES-256-GCM.
The server, and anyone looking at it, sees only:

```
encoding: binary/encrypted   encryption-key-id: netops-1   data: xsjvdgT3Jbls9ASxiCGG...
```

Every process that reads or writes payloads needs the same key (`PAYLOAD_KEY`). A starter without
it can't read the result.

The UI can still show decrypted payloads to people who have the key, through a **codec server**:
a small HTTP service on your own machine. The browser sends encrypted payloads to it and shows
what comes back. The UI itself never sees the key.

A codec is a backstop, not a licence: the course still never puts credentials or full configs
into payloads (Day 7, Day 14). The codec covers what remains: device names, config lines being
pushed, results.

## Walkthrough

### 1. Every activity call names the queue

```python
# file: netops_temporal/workflows/facts.py
            # Day 21: activities run on the device-io workers, not the workflow workers.
            task_queue=DEVICE_IO_TASK_QUEUE,
```

Workflows that share options (`ACTIVITY_OPTIONS`, the saga's `STEP` and `UNDO`) add it to the
dict once. Nautobot calls and `say_hello` go there too: the device-io worker runs every activity.

### 2. `workers/device_io.py`

```python
# file: netops_temporal/workers/device_io.py
        worker = Worker(
            client,
            task_queue=DEVICE_IO_TASK_QUEUE,
            activities=ACTIVITIES,
            activity_executor=executor,
            # Per process: no more device sessions at once than threads to run them (Day 7).
            max_concurrent_activities=SLOTS,
            # Across ALL device-io workers: the server hands out at most 5 activities a second,
            # however many workers you start. Protects AAA and device CPUs from a burst.
            max_task_queue_activities_per_second=5.0,
            # On shutdown, stop taking new activities and give running ones 30 s to finish
            # (a show tech in progress, say) before they're cancelled.
            graceful_shutdown_timeout=timedelta(seconds=30),
        )
        # SIGTERM is what a container runtime (or systemd) sends to stop a process; Ctrl-C is
        # SIGINT. Either way: shut down gracefully instead of dying mid-session.
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.shutdown()))
```

`workers/orchestration.py` is the same shape with `workflows=WORKFLOWS` and no activities. Both
reuse `telemetry()` from `workers/main.py` (Day 20's metrics and tracing). If you run both with
`METRICS_PORT`, give each its own port.

### 3. `codec.py`

```python
# file: netops_temporal/codec.py
    async def encode(self, payloads: Sequence[Payload]) -> list[Payload]:
        return [
            Payload(
                metadata={"encoding": ENCODING, "encryption-key-id": self.key_id.encode()},
                data=self._encrypt(p.SerializeToString()),
            )
            for p in payloads
        ]
```

The whole original payload (its metadata and data) is serialized and encrypted with a fresh
random nonce. `decode` reverses it, refuses payloads that need a different key ID, and passes
through payloads that were never encrypted (from before you turned it on).

### 4. `client.py`: the codec when `PAYLOAD_KEY` is set

```python
# file: netops_temporal/client.py
def data_converter() -> DataConverter:
    """Pydantic for models (Day 3), plus encryption when PAYLOAD_KEY is set (Day 21)."""
    key = os.environ.get("PAYLOAD_KEY")
    if not key:
        return pydantic_data_converter
    return dataclasses.replace(
        pydantic_data_converter, payload_codec=EncryptionCodec(base64.b64decode(key))
    )
```

Workers and starters all connect through `connect()`, so setting `PAYLOAD_KEY` in `.env` turns
encryption on everywhere at once.

### 5. `tools/codec_server.py` and `lab/Containerfile.worker`

The codec server is about 50 lines of `aiohttp`: `POST /decode` and `POST /encode`, plus the CORS
headers that let the UI's page (`http://localhost:8233`) call it.

The Containerfile installs the dependencies in their own layer, copies in either your `src/` or a
solution day (`--build-arg CODE=solutions/day-21`), runs as a non-root user, and starts the
device-io worker.

### 6. Tests

- `test_activities_route_to_device_io_queue`: with only a workflow worker, the activity is pending
  at attempt 1, not failing. Start a device-io worker and the workflow completes.
- `test_device_io_worker_settings` and `test_orchestration_worker_has_no_activities`: the workers'
  settings, without a server.
- `test_codec_roundtrip`, `test_codec_refuses_a_different_key`, and
  `test_encrypted_payload_unreadable_in_history`: the device name appears nowhere in the stored
  history's bytes. `test_plain_payload_readable_in_history` is the control: without the codec,
  it does.
- `test_codec_server_decodes_for_the_ui`.

The shared test fixtures now start two workers, like `workers/main.py`.

## Run it

Make a key and put it in `.env`:

```bash
python -c 'import base64, os; print(base64.b64encode(os.urandom(32)).decode())'
# PAYLOAD_KEY=<that value>   in .env
```

Two terminals, one worker each:

```bash
uv run --env-file .env python -m netops_temporal.workers.orchestration
uv run --env-file .env python -m netops_temporal.workers.device_io
```

Then, in a third:

```bash
uv run --env-file .env python -m netops_temporal.starters.facts bos-rtr-01
```

The starter prints the facts as usual. Now look at what the server stored:
`temporal workflow show --workflow-id facts-bos-rtr-01 -o json`. The input and result payloads
have `"encoding": "YmluYXJ5L2VuY3J5cHRlZA=="` (base64 for `binary/encrypted`) and unreadable data.
The UI shows the same.

## Break it

1. **Stop only the device-io worker.** Ctrl-C it (it logs
   `Beginning worker shutdown, will wait 0:00:30 before cancelling activities`). Start
   `starters.facts nyc-rtr-01`: it waits. `temporal workflow describe --workflow-id facts-nyc-rtr-01`
   shows one pending activity, attempt 1. Nothing fails. Start the device-io worker again: the
   workflow completes within a second.
2. **Stop it in the middle of a show tech.** Run the device-io worker with
   `LAB_MODE=mock MOCK_CLI_DELAY=3`, start `starters.show_tech nyc-acc-01`, and a few seconds in,
   press Ctrl-C. The worker doesn't exit straight away: it finishes the show tech (all 10 commands,
   `resumed_from=0`) and then stops. With a longer show tech than 30 s, it would be cancelled at
   30 s and the next worker would resume it from its heartbeat.
3. **The UI with and without the codec server.** Open `facts-bos-rtr-01` in the UI: encrypted.
   Start the codec server
   (`uv run --env-file .env python -m netops_temporal.tools.codec_server`), then in the UI click
   the glasses icon (top right) → **Codec Server** → `http://127.0.0.1:8888` → apply. Reload: the
   payloads are readable. Stop the codec server and reload: encrypted again.
4. **The device-io worker in a container** (optional, needs podman or docker). From the repo root:

   ```bash
   podman build -f lab/Containerfile.worker --build-arg CODE=solutions/day-21 -t netops-device-io .
   podman run -d --name device-io --env-file .env -e LAB_MODE=mock \
     -e TEMPORAL_ADDRESS=host.containers.internal:7233 -e OUTPUT_DIR=/app/output netops-device-io
   ```

   Stop the device-io worker in your terminal and run `starters.facts` again: the container does
   the work (`podman logs device-io`). `host.containers.internal` is how a container reaches your
   machine. For the live lab, the device addresses in `DEVICE_HOSTS` must be reachable from inside
   the container too (tunnels bound to `127.0.0.1` on your machine aren't). Mock mode avoids that.
   Repeat break 2 with `podman stop -t 40 device-io`: the stop takes about as long as the rest of
   the show tech, because the worker finishes it first. With plain `podman stop`, podman kills
   the worker after 10 s: the show tech is cut off, and once its heartbeat timeout passes it's
   retried on the next worker you start, resuming from its last heartbeat (Day 5). Clean up with
   `podman rm -f device-io`.

## Check yourself

1. Why run workflows and activities on different workers?
2. What happens to a workflow's activities when no device-io worker is running?
3. What's the difference between `max_concurrent_activities` and
   `max_task_queue_activities_per_second`?
4. What does graceful shutdown do with a show tech that's halfway through, and what must the
   thing stopping the worker do for it to work?
5. With the codec, what does the Temporal server store, and who can read it?

<details>
<summary>Answers</summary>

1. They need different things (credentials and network reach vs nothing), and scale and restart
   independently. A deploy of device code doesn't touch the workflow workers.
2. They wait on the `netops-device-io` queue, at attempt 1. No failure, no retries used. They run
   when a device-io worker starts.
3. The first is a limit per worker process. The second is enforced by the server across every
   worker on the queue: the total rate devices see.
4. The worker stops taking new work and gives the show tech up to 30 s to finish. The thing
   sending SIGTERM has to wait at least that long before killing the process (`podman stop -t 40`,
   not the 10 s default).
5. Encrypted payloads (`binary/encrypted`). Only processes with `PAYLOAD_KEY`, or a person whose
   browser uses a codec server that has it.

</details>

## Solution

[`solutions/day-21/`](../../../solutions/day-21/): new `workers/orchestration.py`,
`workers/device_io.py`, `codec.py` and `tools/codec_server.py`; every activity call routed to
`DEVICE_IO_TASK_QUEUE`; `workers/main.py` polls both queues; `client.py` adds the codec when
`PAYLOAD_KEY` is set. Outside the solution: `lab/Containerfile.worker`, `.dockerignore`, and new
settings in `.env.example`. Tests: `tests/test_production_workers.py` and `tests/test_codec.py`.
