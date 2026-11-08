# Day 01 — Lab up, and how Temporal actually runs your code

[← Week 1](../README.md) · [Day 02 →](../day-02-eapi-activity/README.md)

**Time:** 60–90 minutes · **Needs the cEOS lab?** No (Temporal only) · **Solution:** [`solutions/day-01/`](../../../solutions/day-01/)

## Why today matters

Think about the last multi-step change script you wrote: back up the config, push a change,
check BGP, roll back if it's broken. Now picture it dying halfway: your laptop sleeps, the VPN
drops, a device times out. What state is the network in? Which steps ran? Usually you find out by
logging into devices and reading logs.

Temporal's job is to make that question boring. It records every step of your automation as it
happens, so after a crash it knows exactly which steps finished and resumes from there. Today you
won't touch a device. You'll get the lab running and learn the handful of moving parts that make
that possible. Every later day builds on them.

## Concept

### Four pieces

| Temporal term | What it is | Network-ops analogy |
| --- | --- | --- |
| **Workflow** | A Python class whose `run` method decides *what happens next*. It doesn't touch the network itself. | A change ticket with a runbook attached, and a log of every step taken so far |
| **Activity** | A plain Python function that does one piece of real work: SSH to a box, call an API, write a file. | One runbook step, the part that actually touches the network |
| **Worker** | Your Python process. It connects to Temporal, asks for work, and runs your workflow and activity code. | The engineer on shift who picks tickets off the queue and works them |
| **Task Queue** | A named queue on the Temporal server. Starters put work on it; workers poll it. | The queue the tickets sit in |

There's also the **Temporal server** (here, a dev server in a container) and the **client**: any
code that asks the server to start a workflow. Our "starters" are clients.

### Who does what

```
  starter (client)                Temporal server                     worker (your process)
  ────────────────                ───────────────                     ─────────────────────
  "start HelloWorkflow"  ──────▶  writes event 1 to the history
                                  puts a workflow task on      ◀────  polls "netops-orchestration"
                                  "netops-orchestration"       ─────▶ runs HelloWorkflow.run()
                                                                      "please run say_hello"
                                  records the request          ◀────
                                  puts an activity task on     ─────▶ runs say_hello("Manny")
                                  the queue                    ◀────  "it returned Hello, Manny!"
                                  records the result
                                  ...                          ─────▶ runs the workflow again,
                                                                      which now returns the result
  gets "Hello, Manny!"   ◀──────  records "workflow completed"
```

The key idea: **the server keeps the history; the worker keeps nothing.** Each time the
workflow needs to make a decision, the worker gets the history so far, runs your code up to the
next decision, and reports back. If the worker dies, another one (or the same one restarted)
picks up the history and carries on. That's why it's safe to kill a worker at any time, as you'll
do in *Break it*.

### The event history

Everything that happens to a workflow is appended to its **event history**: started, an activity
scheduled, an activity completed, finished. It's the source of truth. The UI and CLI are just
views of it. Day 4 explains how Temporal replays this history to rebuild a workflow's state; for
now, learn to read it.

## Walkthrough

You'll grow `src/netops_temporal/` all month. Today it holds a working "hello" example plus some
helpers you'll use from Day 2. Read it in this order.

### `constants.py`: settings in one place

Everything configurable comes from environment variables, which `uv run --env-file .env` loads
from your `.env` file:

```python
# file: netops_temporal/constants.py
TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")

# Task queues. Workers poll a queue by name; starters send work to it by the same name.
# Everything runs on the orchestration queue until Day 21 splits device I/O onto its own.
ORCHESTRATION_TASK_QUEUE = "netops-orchestration"
DEVICE_IO_TASK_QUEUE = "netops-device-io"
```

A task queue is just a string. There's no "create queue" step: if a worker polls
`netops-orchestration` and a starter sends work to `netops-orchestration`, they've found each other.
A typo on either side means work sits in a queue nobody polls. That's the first thing to check
when a workflow is stuck in Running.

The device inventory is parsed here once, so every later day can look up a device by name:

```python
# file: netops_temporal/constants.py
@dataclass(frozen=True)
class DeviceAddress:
    """Where to reach one device. Ports change from the defaults when you tunnel via a jump host."""

    host: str
    eapi_port: int = 443
    ssh_port: int = 22
...
def parse_device_hosts(raw: str) -> dict[str, DeviceAddress]:
    """Parse "name=host[:eapi_port[:ssh_port]],..." into {name: DeviceAddress}."""
...
DEVICE_HOSTS = parse_device_hosts(os.environ.get("DEVICE_HOSTS") or DEFAULT_DEVICE_HOSTS)
DEVICES = list(DEVICE_HOSTS)


def device_address(device: str) -> DeviceAddress:
    try:
        return DEVICE_HOSTS[device]
    except KeyError:
        raise UnknownDeviceError(
            f"unknown device {device!r}; DEVICE_HOSTS knows {', '.join(DEVICES)}"
        ) from None
```

So `DEVICE_HOSTS=bos-rtr-01=172.20.20.2` gives `device_address("bos-rtr-01")` →
`DeviceAddress(host="172.20.20.2", eapi_port=443, ssh_port=22)`. Behind a jump host,
`lab/tunnels.sh` gives you entries like `bos-rtr-01=127.0.0.1:8441:2201` instead, and nothing
else in the code changes.

Finally, `lab_mode()` says whether to talk to the real lab or replay recorded outputs:

```python
# file: netops_temporal/constants.py
def lab_mode() -> Literal["live", "mock"]:
```

### `mock/` and `fixtures/`: the lab, recorded

These are provided so you can do every day even when the cEOS lab is off: on a train, in
Codespaces, or in CI. With `LAB_MODE=mock`, device helpers return outputs captured from the real
lab (`fixtures/`), and you can fake failures: `MOCK_UNREACHABLE=bos-rtr-01` makes that device act
as if it's down. You won't edit these files; you'll *use* them from Day 2. The table of switches
is in [lab setup → Mock mode](../../../docs/lab-setup.md#mock-mode).

`devices/errors.py` defines three exceptions (`DeviceUnreachableError`, `DeviceAuthError`,
`UnknownDeviceError`) that all device code raises, whatever library it uses. Day 3 explains why.

### The activity: `activities/hello.py`

```python
# file: netops_temporal/activities/hello.py
from temporalio import activity


@activity.defn
async def say_hello(name: str) -> str:
    activity.logger.info("Saying hello to %s", name)
    return f"Hello, {name}!"
```

`@activity.defn` registers the function as an activity named `say_hello`. Otherwise it's a
normal function: in real activities this is where you'd open an SSH session or call an API.
`activity.logger` is a regular Python logger that also tags each line with the workflow and
activity IDs, which helps a lot when a worker runs hundreds of activities at once.

### The workflow: `workflows/hello.py`

```python
# file: netops_temporal/workflows/hello.py
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.hello import say_hello


@workflow.defn
class HelloWorkflow:
    """Day 1 smoke test: proves server, worker and client are wired up."""

    @workflow.run
    async def run(self, name: str) -> str:
        return await workflow.execute_activity(
            say_hello,
            name,
            start_to_close_timeout=timedelta(seconds=10),
        )
```

Line by line:

- `@workflow.defn` on a class makes it a workflow type, named `HelloWorkflow` after the class.
- `@workflow.run` marks the entry point. Its arguments are the workflow's input; its return value
  is the workflow's result.
- `workflow.execute_activity(say_hello, name, ...)` doesn't call `say_hello` directly. It asks
  the server to schedule the activity, then waits (`await`) for the result. The activity might
  run on this worker or another one, now or after three retries; the workflow doesn't care.
- `start_to_close_timeout` is how long one attempt of the activity may take. Temporal requires
  you to set a timeout on every activity. Day 2 covers the options.
- `imports_passed_through()`: workflow code runs in a **sandbox** that re-imports modules to keep
  workflows deterministic (Day 4). Passing the activity module through tells the sandbox
  "this import is safe, don't reload it". For now: import activities into workflow files this way.

### The worker: `workers/main.py`

```python
# file: netops_temporal/workers/main.py
async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    worker = Worker(
        client,
        task_queue=ORCHESTRATION_TASK_QUEUE,
        workflows=[HelloWorkflow],
        activities=[say_hello],
    )
```

A worker is a connection to the server, a task queue to poll, and the list of workflow and
activity types it can run. **If a type isn't registered here, this worker can't run it**: a
workflow that calls an unregistered activity will sit waiting for a worker that has it. Each day
you'll add the new workflows and activities to these lists.

### The starter: `starters/hello.py`

```python
# file: netops_temporal/starters/hello.py
    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    result = await client.execute_workflow(
        HelloWorkflow.run,
        name,
        id=f"hello-{name.lower()}",
        task_queue=ORCHESTRATION_TASK_QUEUE,
    )
    print(result)
```

`execute_workflow` starts the workflow and waits for its result. (`start_workflow` starts it and
returns a handle immediately; you'll use it later.) Two arguments matter every time:

- `id`: the **workflow ID**, a name you choose. While a workflow with this ID is running, Temporal
  won't start a second one with the same ID. Pick IDs that mean something (`backup-bos-rtr-01`);
  you'll use that guarantee as a lock in Week 2.
- `task_queue`: must match the worker's queue.

### `tools/check_lab.py`

A small script that tests every connection the course needs: Temporal, eAPI and SSH to each
device, and Nautobot. Run it whenever something seems off.

## Run it

Do the [lab setup](../../../docs/lab-setup.md) first, at least steps 1–2 (Python and Temporal).

```bash
cp .env.example .env          # if you haven't already
uv sync
./lab/start-temporal.sh
uv run --env-file .env python -m netops_temporal.tools.check_lab
```

No cEOS lab or Nautobot yet? Run `LAB_MODE=mock uv run --env-file .env python -m netops_temporal.tools.check_lab`
instead: only the Temporal line needs to be `OK` today.

Terminal 1, the worker (leave it running):

```bash
uv run --env-file .env python -m netops_temporal.workers.main
```

Terminal 2, the starter:

```bash
uv run --env-file .env python -m netops_temporal.starters.hello Manny
```

Expected output: `Hello, Manny!`

Open http://localhost:8233, click the `hello-manny` workflow, and look at the timeline and the
event history. Then do the same from the CLI:

```bash
temporal workflow list
temporal workflow describe --workflow-id hello-manny
temporal workflow show --workflow-id hello-manny          # the event history
temporal workflow show --workflow-id hello-manny -o json  # the same, as JSON (Day 6 uses this)
```

No `temporal` CLI on your Mac? Use the one inside the container:
`podman exec -it temporal-dev temporal workflow list --address localhost:7233`.

`temporal workflow show` prints:

```
  ID  Type
   1  WorkflowExecutionStarted
   2  WorkflowTaskScheduled
   3  WorkflowTaskStarted
   4  WorkflowTaskCompleted
   5  ActivityTaskScheduled
   6  ActivityTaskStarted
   7  ActivityTaskCompleted
   8  WorkflowTaskScheduled
   9  WorkflowTaskStarted
  10  WorkflowTaskCompleted
  11  WorkflowExecutionCompleted
```

Read it as a conversation:

| Events | What happened | Who caused it |
| --- | --- | --- |
| 1 | The starter asked to run `HelloWorkflow("Manny")` | client |
| 2–4 | The server queued a **workflow task**, your worker picked it up, ran `run()` until it hit `execute_activity`, and replied "schedule `say_hello`" | server → worker |
| 5 | The server recorded that request and queued an **activity task** | server (from the worker's command) |
| 6–7 | Your worker ran `say_hello` and reported the return value | worker |
| 8–10 | New information, so another workflow task: the worker ran `run()` again, got the activity result, and the method returned | server → worker |
| 11 | The workflow's result was recorded | server (from the worker's command) |

Notice that **workflow tasks** (decide what to do) and **activity tasks** (do it) are separate.
That split is what lets Temporal retry a failed activity without re-running the decisions around it.

## Break it

1. **No worker.** Stop the worker (Ctrl-C). Run the starter again with a new name:
   `... starters.hello Ada`. It hangs. In the UI, `hello-ada` is **Running** with only events
   1–2: a workflow task is scheduled, but nobody is polling the queue. Nothing is wrong; the work
   is just waiting.
2. **Worker comes back.** Start the worker again. Within a second the starter prints
   `Hello, Ada!` and the workflow completes. Nothing was lost while no worker was running.
3. **Server restart.** `podman restart temporal-dev`, then refresh the UI. Your workflows and
   their histories are still there, because the dev server stores them in a database file
   (`--db-filename` in `lab/start-temporal.sh`).
4. **Wrong queue.** In `starters/hello.py`, temporarily change `task_queue` to `"netops-typo"`
   and run it. It hangs forever, even with the worker running. Look at the workflow in the UI:
   the task queue name is shown, and clicking it shows **no pollers**. Change it back, and
   terminate the stuck workflow: `temporal workflow terminate --workflow-id hello-<name>`.

## Check yourself

1. For each of the 11 events in `hello-manny`'s history, who produced it: the client, the server,
   or the worker?
2. Why is it safe to kill a worker in the middle of a workflow?
3. A workflow has been "Running" for ten minutes and nothing is happening. Name two causes you
   saw today.
4. What stops two starters from running `HelloWorkflow` for the same name at the same time?

<details>
<summary>Answers</summary>

1. 1 = client (the start request). 2, 5, 8 = server (scheduling tasks; 5 is created from the
   worker's "schedule activity" command). 3–4, 6–7, 9–10 = worker (picking up tasks and reporting
   results). 11 = server, recording the worker's "complete workflow" command.
2. The worker holds no state that matters. The history lives on the server. A restarted worker
   (or any other worker on the same queue) gets the history and carries on from the last
   recorded event.
3. No worker is polling that task queue (none running, or a typo in the queue name), or the
   worker doesn't have the workflow/activity type registered.
4. The workflow ID. While `hello-manny` is running, starting another workflow with the ID
   `hello-manny` fails.

</details>

## Solution

There's nothing to write today, so [`solutions/day-01/`](../../../solutions/day-01/) is
identical to the `src/` you started with. From Day 2, each day's solution is the complete code as
it should look at the end of that day. See
[Using the solutions](../../../README.md#using-the-solutions) for how to compare your code with
it, or run it directly.

Write one line in [`LEARNING.md`](../../../LEARNING.md) about what surprised you, then commit:
`git commit -am "day 01: lab up"`.
