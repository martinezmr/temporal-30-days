# Day 14 — Mini-project: NetworkComplianceOrchestrator v0

[← Day 13](../day-13-entity-workflows/README.md) · [Week 3 →](../../week-3/README.md)

**Time:** 90–120 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-14/`](../../../solutions/day-14/)

## Why today matters

Compliance is the job nobody finishes: every device should run the approved EOS version and have
the standard config lines (NTP, logging), and every week a few quietly drift. Someone runs a
script, gets a wall of output, and fixes what they have time for. Nobody can say, right now,
which devices are out of policy.

Today you put Week 2 together into the first version of `NetworkComplianceOrchestrator`: a
long-running workflow that checks every device against its intent (Nautobot) and the compliance
policy on a schedule, keeps the result as state you can query at any moment, takes a "check now"
signal and an interval update, and continues-as-new so it can run for months. It only *reports*
drift today. Week 3 adds remediation.

## Concept

### The orchestrator decides; activities do the I/O

The orchestrator is one workflow (ID `orchestrator`) whose loop is:

1. For every device, in parallel: fetch intent, fetch facts, check the running config against the
   policy lines for the device's role.
2. Work out the drift.
3. Store the result per device. Wait for the interval or a `force_check` signal. Repeat.

Step 1 talks to the network and Nautobot, so it's all **activities** (two from Week 1, one new).
Step 2 is just comparing values. Deterministic code like that can run **inside the workflow**:
the same inputs (from history) always give the same answer on replay. Keeping it as a plain
function, `compute_drift`, means it's unit-tested without Temporal at all.

### Two kinds of drift

| Kind | Compared | Source of truth |
| --- | --- | --- |
| `version` | `show version` vs `target_version` | Nautobot custom field (Day 7) |
| `config` | Running config vs the policy lines for the device's role | `policies.py` |

The policy: every device needs `ntp server 192.0.2.10`; routers also need
`logging host 192.0.2.50`. No lab device has these lines yet, so on the first run **every device
shows config drift**, and `nyc-acc-01` also has version drift (Nautobot says `4.33.1F`, it runs
`4.32.0F`). That's deliberate: Week 3's remediation will fix the config drift for real.

### Keep big data out of history

Running configs are large, and can contain secrets. They never cross into the workflow. The new
activity, `check_config_compliance`, reads the config on the worker and returns **only the
missing lines**. History holds the answer, not the evidence.

### One bad device never stops the cycle

As on Day 7, a device whose activities fail gets status `unknown` with the reason. The other
devices are still checked, and the orchestrator keeps running.

### The mock lab remembers pushes

From today the mock lab has a little state of its own, `mock/state.py`, a JSON file under
`OUTPUT_DIR`. Lines "pushed" to a mock device show up in its running config from then on, even
across worker restarts. Nothing pushes yet; Day 17 does. A test uses it today to fake a compliant
device.

## Walkthrough

### 1. `policies.py`

```python
# file: netops_temporal/policies.py
POLICIES: dict[str, list[str]] = {
    "access": ["ntp server 192.0.2.10"],
    "router": ["ntp server 192.0.2.10", "logging host 192.0.2.50"],
}
```

Plain data, so the workflow can import it. (On Day 22 the compliance team takes ownership of it
behind a Nexus service.)

### 2. `models.py`: drift, state, and the orchestrator's input

```python
# file: netops_temporal/models.py
class DriftReport(BaseModel):
    """One way a device differs from its intent."""

    device: str
    kind: Literal["version", "config"]
    expected: str
    actual: str
    missing_lines: list[str] = Field(default_factory=list)
```

```python
# file: netops_temporal/models.py
class ComplianceState(BaseModel):
    """What the orchestrator knows about one device after its latest check."""

    device: str
    status: Literal["compliant", "drifted", "unknown"]
    drift: list[DriftReport] = Field(default_factory=list)
    checked_at: datetime
    error: str | None = None


class OrchestratorInput(BaseModel):
    devices: list[str] = Field(default_factory=lambda: list(DEVICES))
    interval_seconds: int = 900
    max_cycles_per_run: int = 50
    # Handed over by continue-as-new.
    state: dict[str, ComplianceState] = Field(default_factory=dict)
    cycles: int = 0
```

### 3. `activities/compliance.py`: only the missing lines come back

```python
# file: netops_temporal/activities/compliance.py
@activity.defn
def check_config_compliance(req: ComplianceCheckRequest) -> list[str]:
    """Return the required lines the running config doesn't have.

    Only the missing lines come back. The config itself stays on the worker, out of workflow
    history (it's large, and it may contain secrets).
    """
```

```python
# file: netops_temporal/activities/compliance.py
    present = {line.strip() for line in config.splitlines()}
    return [line for line in req.required_lines if line not in present]
```

It reuses Day 7's `get_running_config` (NAPALM) and the same error mapping as the other
activities.

### 4. `drift.py`: pure comparison

```python
# file: netops_temporal/drift.py
def compute_drift(
    intent: DeviceIntent, facts: DeviceFacts, missing_lines: list[str]
) -> list[DriftReport]:
    drift = []
    if facts.version != intent.target_version:
```

No clock, no I/O, no randomness: safe to call from a workflow.

### 5. `workflows/orchestrator.py`: check one device

```python
# file: netops_temporal/workflows/orchestrator.py
    async def check_device(self, device: str) -> ComplianceState:
        """Intent and facts in parallel, then the config check for the device's role.

        An unreachable device becomes `unknown` with the reason: one bad device never stops
        the cycle for the others.
        """
        try:
            intent, facts = await asyncio.gather(
                workflow.execute_activity(
                    fetch_device_intent, IntentRequest(device=device), **ACTIVITY_OPTIONS
                ),
                workflow.execute_activity(
                    get_device_facts, FactsRequest(device=device), **ACTIVITY_OPTIONS
                ),
            )
            missing = await workflow.execute_activity(
                check_config_compliance,
                ComplianceCheckRequest(device=device, required_lines=POLICIES[intent.role]),
                **ACTIVITY_OPTIONS,
            )
        except ActivityError as err:
            return ComplianceState(
                device=device, status="unknown", checked_at=workflow.now(), error=str(err.cause)
            )
        # Deterministic logic can live in the workflow. Only I/O needs to be an activity.
        drift = compute_drift(intent, facts, missing)
```

The config check needs the intent first (to know the role), so it runs after the `gather`.
`ACTIVITY_OPTIONS` is a 60-second timeout and at most 3 attempts.

### 6. The loop

```python
# file: netops_temporal/workflows/orchestrator.py
        while True:
            # One cycle: check every device in parallel (Day 7's fan-out).
            results = await asyncio.gather(*(self.check_device(d) for d in inp.devices))
            self.state.update({s.device: s for s in results})
            self._cycles += 1
            cycles_this_run += 1
```

Then the Day 8 wait (`force_check` or the interval), and the Day 12 continue-as-new, handing over
`state`, `cycles` and `interval_seconds` with `inp.model_copy(update={...})`. The handlers are the
week's patterns again:

- query `compliance()`: the whole state, per device;
- query `cycles()`: how many cycles have run;
- signal `force_check()`;
- update `set_interval(SetIntervalRequest)`, with Day 10's 30–86400 s validator.

### 7. Register, and a starter

`NetworkComplianceOrchestrator` goes into `WORKFLOWS`, `check_config_compliance` into
`ACTIVITIES`. `starters/orchestrator.py` has `start`, `status`, `force-check` and `interval`.

## Run it

Make sure the course Nautobot is running and seeded (Day 7). Restart the worker, then:

```bash
uv run --env-file .env python -m netops_temporal.starters.orchestrator start
uv run --env-file .env python -m netops_temporal.starters.orchestrator status
```

Expected (live lab or mock, the same):

```
after 1 cycle(s):
  bos-acc-01  drifted   config: 1 missing (want 1 policy line(s) present)
  bos-rtr-01  drifted   config: 2 missing (want 2 policy line(s) present)
  nyc-acc-01  drifted   version: 4.32.0F (want 4.33.1F); config: 1 missing (want 1 policy line(s) present)
  nyc-rtr-01  drifted   config: 2 missing (want 2 policy line(s) present)
```

In the UI, open `orchestrator`: four devices' worth of activities ran in parallel, and the
workflow is now waiting on a 900 s timer. The worker log has a `cycle 1: {...}` line.

## Break it

1. **One device down.** Restart the worker with one device pointing at a dead port, for example
   by changing `nyc-rtr-01`'s eAPI port in `DEVICE_HOSTS` to `9999` (mock:
   `MOCK_UNREACHABLE=nyc-rtr-01`). Run `force-check`, wait a few seconds for the retries, then
   `status`:
   `nyc-rtr-01  unknown   DeviceUnreachableError: nyc-rtr-01: Socket error during eAPI connection: [Errno 61] Connection refused`.
   The other three were checked as normal.
2. **Make a device compliant.** Mock mode only, for now: with the worker stopped, run
   `python -c 'from netops_temporal.mock import state; state.apply_lines("bos-acc-01", ["ntp server 192.0.2.10"])'`
   (with `scripts/solution.sh 14` in front, from the repo root), start the worker with
   `LAB_MODE=mock` and `force-check`. `bos-acc-01` is now `compliant`. `state.reset()` undoes it.
3. **A bad interval.** `... orchestrator interval 10` fails with `WorkflowUpdateFailedError`, and
   nothing is recorded.
4. **Find the drift in history.** Click an `ActivityTaskCompleted` for `check_config_compliance`:
   its result is just the missing lines. Search the history for `hostname`: no running config
   anywhere.

## Check yourself (end-of-week checkpoint)

1. Why can `compute_drift` run inside the workflow, when `get_device_facts` can't?
2. Why does `check_config_compliance` return missing lines instead of the config?
3. How does the orchestrator stay correct if a worker restarts in the middle of a cycle?
4. Which Week 2 feature would you use to: (a) check now, (b) change the interval and know it
   worked, (c) see the current state, (d) run for a year?
5. What happens to the state when the orchestrator continues as new?

<details>
<summary>Answers</summary>

1. It's deterministic: no I/O, clock or randomness, and its inputs come from activity results that
   are in history. `get_device_facts` talks to a device, so its result can differ each time; it
   must be an activity so its result is recorded once.
2. Configs are large and may contain secrets, and history keeps payloads for the life of the
   workflow. The workflow only needs the answer.
3. The new worker replays history: completed activities return their recorded results, and
   activities that were in flight are retried. The cycle carries on where it was.
4. (a) A signal (`force_check`). (b) An update with a validator (`set_interval`). (c) A query
   (`compliance`). (d) Continue-as-new.
5. It's handed over in the new run's input (`OrchestratorInput.state`), and `__init__` (with
   `@workflow.init`) loads it before anything else runs.

</details>

## Solution

[`solutions/day-14/`](../../../solutions/day-14/): new `policies.py`, `drift.py`,
`mock/state.py`, `activities/compliance.py`, `workflows/orchestrator.py` and
`starters/orchestrator.py`; drift and state models in `models.py`; the mock lab's running config
includes pushed lines. Tests: `test_drift.py` (pure), `test_mock_state.py`, and
`test_orchestrator.py` (expected drift, unreachable device, a compliant device, `force_check`,
the interval timer, the validator, continue-as-new).
