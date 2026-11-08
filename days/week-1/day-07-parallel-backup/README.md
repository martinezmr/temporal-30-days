# Day 07 — Mini-project: parallel config backup (NAPALM) + intent (Nautobot)

[← Day 06](../day-06-testing/README.md) · [Week 2 →](../../week-2/README.md)

**Time:** 90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-07/`](../../../solutions/day-07/)

## Why today matters

The nightly backup job: pull the running config from every device, save it with a timestamp,
and note what each device is *supposed* to run according to the source of truth. Done one device
at a time, 500 devices take all night. Run in parallel with a script, one failure tends to take
down the whole run, or gets lost in a wall of output.

Today you put the week together into a workflow that backs up all devices **in parallel**, pairs
each backup with its **intent from Nautobot**, and reports **partial failure** as data: "3 of 4
backed up, `nyc-rtr-01` unreachable". It doesn't crash, and it doesn't hide the failure. This
`device state + intent` pairing is the seed of the compliance orchestrator you'll build in Week 2.

## Concept

### Fan-out inside a workflow

Workflow code is `async`, so `asyncio.gather` works in it, and it's deterministic: gathering
coroutines that each `execute_activity` just **schedules** those activities. All the "schedule"
commands go to the server in the same workflow task, and workers pick the activities up in
parallel. The parallelism happens on the workers' thread pools (`max_workers=10` per worker), not
in the workflow.

```
ConfigBackupWorkflow
 ├─ backup_one("bos-rtr-01") ─┬─ backup_running_config   (NAPALM, eAPI)
 │                            └─ fetch_device_intent     (pynautobot)
 ├─ backup_one("bos-acc-01") ─┬─ ...
 ├─ backup_one("nyc-rtr-01") ─┬─ ...
 └─ backup_one("nyc-acc-01") ─┴─ ...      → 8 activities, all scheduled at once
```

### Partial failure: fail the workflow, or report?

When one of eight activities runs out of retries, its `await` raises `ActivityError` in the
workflow. You choose what that means:

- **Let it propagate**: the whole workflow fails. Right when the steps depend on each other
  ("don't push config if the backup failed").
- **Catch it and record it**: the workflow completes with a report that lists the failure. Right
  when the items are independent, as backups of different devices are.

Today is the second kind. One detail matters: catch only **`ActivityError`** (a device or API
problem). A different exception means a bug in your workflow code, or a **cancellation**. Hiding
those would make a cancelled backup look "successful with failures".

### Why NAPALM for backups

NAPALM gives the same functions on every vendor: `get_config()`, `get_facts()`, and later
`load_merge_candidate()` / `compare_config()` / `commit_config()` / `rollback()`. That last set is
why it's here: Day 17 builds a safe config push on it. Its EOS driver talks to eAPI through
pyeapi, so it uses the same port as Day 2. One quirk: the driver connects **lazily**. `open()` can
succeed and the first real call fail with a pyeapi error, so the error translation has to wrap
both. (The solution's tests caught exactly this against the real lab.)

### Nautobot as intent

pynautobot is the Python client for Nautobot's REST API. `lab/nautobot/seed.py` gave each device a
role, a location and a custom field `target_version`. The activity turns those into a
`DeviceIntent` model. Nautobot is an outside system like any device, so the lookup is an activity
with its own retries.

## Walkthrough

### 1. `devices/napalm_eos.py`: running config via NAPALM

```python
# file: netops_temporal/devices/napalm_eos.py
    address = device_address(device)
    driver = get_network_driver("eos")(
        hostname=address.host,
        username=DEVICE_USERNAME,
        password=DEVICE_PASSWORD,
        timeout=10,
        optional_args={"transport": "https", "port": address.eapi_port},
    )
    # The EOS driver connects lazily: open() can succeed and the first real call fail.
    # So translate errors from both, whether NAPALM wrapped them or not.
    try:
        driver.open()
        try:
            return driver.get_config(retrieve="running")["running"]
        finally:
            driver.close()
    except (ConnectionException, pyeapi.eapilib.ConnectionError) as err:
        if "Unauthorized" in str(err):
            raise DeviceAuthError(f"{device}: {err}") from err
        raise DeviceUnreachableError(f"{device}: {err}") from err
```

### 2. `sot/nautobot.py`: intent via pynautobot

```python
# file: netops_temporal/sot/nautobot.py
    device_address(device)  # unknown names fail fast, before any API call
    api = pynautobot.api(NAUTOBOT_URL, token=NAUTOBOT_TOKEN)
    # depth=1 returns role and location with their names, not just their IDs.
    record = api.dcim.devices.get(name=device, depth=1)
    if record is None:
        raise UnknownDeviceError(f"{device} is in DEVICE_HOSTS but not in Nautobot")
    return DeviceIntent(
        device=device,
        role=record.role.name,
        location=record.location.name,
        target_version=record.custom_fields["target_version"],
    )
```

`sot/` ("source of truth") is a new package, next to `devices/`: one for what the network *is*,
one for what it *should be*. It has a mock path at the top like the device helpers.

### 3. `models.py`: requests, intent, and a report that can hold failures

```python
# file: netops_temporal/models.py
class DeviceIntent(BaseModel):
    """What Nautobot says a device should be."""

    device: str
    role: str
    location: str
    target_version: str


class BackupRequest(BaseModel):
    devices: list[str] = Field(default_factory=lambda: list(DEVICES))
...
class DeviceBackupResult(BaseModel):
    device: str
    ok: bool
    backup_path: str | None = None
    intent: DeviceIntent | None = None
    error: str | None = None


class BackupReport(BaseModel):
    started_at: datetime
    results: list[DeviceBackupResult]

    @property
    def succeeded(self) -> list[str]:
        return [r.device for r in self.results if r.ok]
```

`BackupRequest()` with no arguments means "all devices"; the default list is filled in when the
*starter* builds the request, so the payload in history always names the devices explicitly.
`BackupConfigRequest(device, timestamp)` and `IntentRequest(device)` are the activities' single
input models.

### 4. `activities/backup.py`: two small activities

```python
# file: netops_temporal/activities/backup.py
@activity.defn
def backup_running_config(req: BackupConfigRequest) -> str:
    """Save the running config to OUTPUT_DIR/backups/<device>/<timestamp>.cfg; return the path."""
...
    path = OUTPUT_DIR / "backups" / req.device / f"{req.timestamp}.cfg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config)
    return str(path)
```

As on Day 5, the config goes to a file and history only stores the path. Auth and unknown-device
errors become non-retryable `ApplicationError`s, as on Day 3. `fetch_device_intent` wraps
`get_device_intent` the same way.

### 5. `workflows/backup.py`: fan out, then collect

```python
# file: netops_temporal/workflows/backup.py
    @workflow.run
    async def run(self, req: BackupRequest) -> BackupReport:
        started_at = workflow.now()
        # One timestamp for the whole run, from workflow time (Day 4), so every file name
        # is the same on replay.
        timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
        # Start every device at once. gather() is safe in a workflow: it only schedules
        # activities; they run in parallel on the workers' thread pools.
        results = await asyncio.gather(
            *(self.backup_one(device, timestamp) for device in req.devices)
        )
```

And for each device:

```python
# file: netops_temporal/workflows/backup.py
    async def backup_one(self, device: str, timestamp: str) -> DeviceBackupResult:
        """Backup and intent for one device, run side by side. Failures become data."""
        backup, intent = await asyncio.gather(
            workflow.execute_activity(
                backup_running_config,
                BackupConfigRequest(device=device, timestamp=timestamp),
                **ACTIVITY_OPTIONS,
            ),
            workflow.execute_activity(
                fetch_device_intent, IntentRequest(device=device), **ACTIVITY_OPTIONS
            ),
            return_exceptions=True,
        )
        errors = []
        for outcome in (backup, intent):
            if isinstance(outcome, ActivityError):
                errors.append(str(outcome.cause))
            elif isinstance(outcome, BaseException):
                raise outcome  # a bug or a cancellation, not a device problem: don't hide it
```

- `return_exceptions=True` makes `gather` return exceptions as values instead of raising the
  first one. Both activities always finish, and you inspect each outcome.
- `outcome.cause` is the activity's own error (e.g. `DeviceUnreachableError: nyc-rtr-01: ...`),
  which is more useful in a report than the `ActivityError` wrapper.
- `ACTIVITY_OPTIONS` (60 s start-to-close, 3 attempts) is shared by both calls. A plain dict
  keeps the two calls consistent.
- `backup_one` is an ordinary `async def` method on the workflow class: a helper, not a separate
  workflow.

### 6. Register, and a starter that prints a table

Add `ConfigBackupWorkflow`, `backup_running_config` and `fetch_device_intent` to `WORKFLOWS` and
`ACTIVITIES` in `workers/main.py`. `starters/backup.py` runs the workflow with the ID
`config-backup`. Because only one workflow per ID can run at a time, two people can't start
overlapping backups by accident.

## Run it

Needs the lab and a seeded Nautobot, or `LAB_MODE=mock`. Restart the worker, then:

```bash
uv run --env-file .env python -m netops_temporal.starters.backup
```

Expected (live; under a second through the tunnels):

```
Backup started 2026-11-08 00:41:05 UTC: 4 ok, 0 failed
  OK    bos-rtr-01  target 4.32.0F  output/backups/bos-rtr-01/20261108T004105Z.cfg
  OK    bos-acc-01  target 4.32.0F  output/backups/bos-acc-01/20261108T004105Z.cfg
  OK    nyc-rtr-01  target 4.32.0F  output/backups/nyc-rtr-01/20261108T004105Z.cfg
  OK    nyc-acc-01  target 4.33.1F  output/backups/nyc-acc-01/20261108T004105Z.cfg
```

Notice `nyc-acc-01`'s target is `4.33.1F` while it runs `4.32.0F` (Day 2). That's the drift
Week 2's orchestrator will detect.

In the UI, open `config-backup` and switch to the **Timeline** view: eight activity bars starting
together. In the history, all eight **ActivityTaskScheduled** events come right after the first
**WorkflowTaskCompleted**, before any activity completes.

## Break it

1. **One device down.** Stop `nyc-rtr-01` (or `MOCK_UNREACHABLE=nyc-rtr-01` and restart the
   worker). The workflow still **Completes**, and the report shows:

   ```
   Backup started ...: 3 ok, 1 failed
     FAIL  nyc-rtr-01  target 4.32.0F  DeviceUnreachableError: nyc-rtr-01: Socket error during eAPI connection: [Errno 61] Connection refused
   ```

   The intent lookup for `nyc-rtr-01` still succeeded, so the target is shown. In the history,
   that device's backup activity shows 3 attempts.
2. **Wrong password.** `DEVICE_PASSWORD=wrong` in `.env`, restart the worker, back up one device:
   `FAIL  bos-acc-01  target 4.32.0F  AuthError: auth failed for bos-acc-01`, after **one**
   attempt. Then try it on a copy of the solution's `devices/napalm_eos.py` with the
   `pyeapi.eapilib.ConnectionError` removed from the `except`. The same wrong password is retried
   3 times. That's the lazy-connection quirk from *Concept*.
3. **Nautobot down.** `podman compose -f lab/nautobot/compose.yml stop nautobot`. Every
   device's intent lookup retries 3 times and fails, so every device is reported failed, but the
   backup files are still written. Start Nautobot again.
4. **Starve the thread pool.** Set `max_workers=2` in the worker, restart it, and run the backup
   again. In the **Timeline** view the eight activities now start two at a time instead of all
   together. The rest wait in the task queue. The pool size is a real limit on how many devices
   one worker talks to at once. Put it back to 10.

## Check yourself (end-of-week checkpoint)

1. Open the `config-backup` history and explain every event: who produced it, and why it's in
   that position.
2. Why is `asyncio.gather` allowed in a workflow, when Day 4 banned so many other things?
3. Why catch only `ActivityError` and re-raise everything else?
4. Why is the timestamp computed once in the workflow instead of in each activity?
5. When would you *want* one device's failure to fail the whole workflow?

<details>
<summary>Answers</summary>

1. 1 WorkflowExecutionStarted (client). 2–4 the first workflow task (server schedules, worker
   runs `run()` up to the gathers and replies with 8 ScheduleActivityTask commands). 5–12
   ActivityTaskScheduled ×8 (server, from those commands). Then for each activity
   ActivityTaskStarted + ActivityTaskCompleted (worker; Started is written when the attempt
   finishes, with its attempt number), interleaved with workflow tasks as results arrive. Finally
   a workflow task whose completion produces WorkflowExecutionCompleted with the report.
2. It's deterministic: the same coroutines schedule the same activities in the same order on
   every replay, and results come from history.
3. `ActivityError` means a device or API failed, which is worth reporting. Anything else is a bug
   or a cancellation; swallowing it would hide real problems and make a cancelled run look
   finished.
4. Determinism and consistency: `workflow.now()` is replay-safe, and every file from one run
   shares one timestamp. Activity clocks would differ per device and per retry.
5. When later steps depend on it, e.g. a config push workflow must not continue if its pre-change
   backup failed.

</details>

## Solution

[`solutions/day-07/`](../../../solutions/day-07/): `devices/napalm_eos.py`, `sot/nautobot.py`,
the new models, `activities/backup.py`, `workflows/backup.py`, `starters/backup.py`, the worker
lists, and `tests/test_backup.py` (parallelism, partial failure, deterministic timestamps, and
NAPALM's lazy-connection errors). `tests/histories/config_backup.json` is a live run, now replayed
on every test run.

Write your end-of-week line in [`LEARNING.md`](../../../LEARNING.md). Week 2 starts making
workflows that live for days.
