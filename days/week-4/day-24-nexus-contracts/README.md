# Day 24 — Nexus contracts: changing a service without breaking its callers

[← Day 23](../day-23-nexus-async/README.md) · [Day 25 →](../day-25-llm-activity/README.md)

**Time:** 75 minutes · **Needs the cEOS lab?** No (`LAB_MODE=mock`) · **Solution:** [`solutions/day-24/`](../../../solutions/day-24/)

## Why today matters

The compliance team has two new rules. Every remediation must carry a **change ticket**. And
they won't touch a device that isn't in their inventory. Both are reasonable, and both mean
changing a service that your orchestrator, and maybe other teams' workflows, call every few
minutes.

Each team deploys on its own schedule, so for a while an old caller will be talking to a new
handler. Today is about changing the contract so that this still works, and about failing in a
way the caller can act on when a request can't succeed.

Network analogy: a published API, like eAPI or Nautobot's REST API. A new release adds optional
fields and new endpoints. It doesn't rename the ones your scripts already use. And a 400 (your
request is wrong) means something different from a 503 (try again later).

## Concept

### The compatibility rules

At any moment, either side might be running old code. A change is safe if it works in both
directions:

| Change | Safe? | Why |
| --- | --- | --- |
| Add an optional field with a default | Yes | Old callers leave it out, and the handler uses the default |
| Add an operation | Yes | Old callers just don't call it |
| Make a field required, or remove or rename it | **No** | Old callers' requests no longer decode |
| Rename or remove an operation | **No** | Old callers ask for an operation that doesn't exist |
| Change an operation's input or output type | **No** | Same as renaming fields, all at once |

For a breaking change, add a new operation (`remediate_v2`), move callers over, and remove the old
one when nobody uses it. The rules live in the contract module's docstring, where anyone changing
it will read them.

### Errors are part of the contract

A caller needs to know one thing about a failure: could trying again ever help? The handler says
so with the error's type:

| The handler raises | Meaning | Retried? | Example today |
| --- | --- | --- | --- |
| `HandlerError(type=BAD_REQUEST)` | The request can never work | No | Unknown device |
| `OperationError(state=FAILED)` | Understood, and refused | No | No change ticket |
| `HandlerError(type=INTERNAL)`, or any other exception | Something broke on the handler's side | Yes | Database down |

A retried error keeps going until it works, or until the caller's operation timeout
(`schedule_to_close_timeout=` on `execute_operation`) runs out. Day 22's Break it showed what
"retried forever" looks like.

Either way, the caller gets a `NexusOperationError`, and the handler's message is in its `cause`.
The orchestrator already turns that into the device's remediation outcome (Day 23), so a refused
remediation shows up in `status` and the cycle carries on.

### Cancellation is part of it too

Day 23 showed what a cancel does to a workflow-backed operation: it cancels the handler's
workflow, which decides how to stop (the saga rolls back), and the caller has to wait for that. A
termination sends nothing. Callers rely on both, so they go in the contract as well.

## Walkthrough

### 1. `models.py`: an optional field

```python
# file: netops_temporal/models.py
class RemediationRequest(BaseModel):
    device: str
    missing_lines: list[str]
    dry_run: bool = True
    # Day 24: added to the Nexus contract. Optional with a default, so callers built before it
    # still send valid requests.
    change_ticket: str | None = None
```

`OrchestratorInput` gets a `change_ticket` too, and the orchestrator puts it on every
`RemediationRequest`. The starter takes it as `--ticket CHG42`.

### 2. `nexus/handler.py`: typed errors

```python
# file: netops_temporal/nexus/handler.py
        # Day 24: typed errors, so callers know whether trying again could ever help.
        if req.device not in DEVICES:
            # Can never work: BAD_REQUEST fails the operation at once, with no retries.
            raise nexusrpc.HandlerError(
                f"unknown device {req.device!r}", type=nexusrpc.HandlerErrorType.BAD_REQUEST
            )
        if os.environ.get("REQUIRE_TICKET") == "1" and not req.change_ticket:
            # Understood, and refused by the team's change rules: the operation fails.
            raise nexusrpc.OperationError(
                f"{req.device}: remediation needs a change ticket",
                state=nexusrpc.OperationErrorState.FAILED,
            )
```

These checks run in the handler, before any workflow starts. So an unknown device never gets a
`remediate-config-lab-sw-99` workflow in the compliance namespace. The ticket also goes in the
remediation's static details (Day 20), for the compliance team's audit trail.

`REQUIRE_TICKET` is the compliance team's setting, on their worker: turning it on is their
deploy, not yours.

### 3. `nexus/service.py`: the rules, written down

The contract's docstring now lists the compatibility rules and what each error type means. It's
the file both teams import, so it's the one place both will read.

### 4. The tests

`tests/test_nexus.py` has a small `AskForRemediation` workflow that calls `remediate` directly:

- `test_unknown_device_bad_request_not_retried`: fails at once with
  `HandlerError: unknown device 'lab-sw-99'`, and no workflow starts. The test gives up after 20
  seconds, so a retried error would fail it instead of hanging.
- `test_missing_ticket_operation_failed`: with `REQUIRE_TICKET=1`, no ticket fails the operation,
  and a ticket lets it through (and shows in the workflow's details). An orchestrator without a
  ticket reports the refusal for the device, and keeps running.
- `test_old_caller_without_ticket_still_works`: sends `RemediationRequestV1`, the request as it
  was before today, without `change_ticket`. It still works. This test guards the contract: it
  fails if anyone makes the field required.

## Run it

Restart the compliance worker with the new rule turned on, and the main worker as usual:

```bash
REQUIRE_TICKET=1 uv run --env-file .env python -m netops_temporal.workers.compliance
```

Terminate any old `orchestrator` and `upgrade-nyc-acc-01`, then `starters.orchestrator start`
and `status`. Every drifted device shows
`-> config: <device>: remediation needs a change ticket`. The orchestrator is fine: it reported
the refusal and will try again next cycle. Terminate it (and the upgrade), then start it with a
ticket:

```bash
uv run --env-file .env python -m netops_temporal.starters.orchestrator start --ticket CHG42
```

`status` shows the dry runs again. In the UI, open `remediate-config-bos-acc-01` in the
`compliance` namespace: its details start with `Change ticket: CHG42`.

## Break it

Both of these change only the compliance team's side: restart only the compliance worker
afterwards, and leave the main worker running the old code, like a team that hasn't deployed yet.

1. **Rename an operation.** In `nexus/service.py` and `nexus/handler.py`, rename `remediate` to
   `remediate_config`. Restart the compliance worker and `force-check`. Every drift now reports
   `config: Nexus service definition 'ComplianceService' has no operation 'remediate'. There are
   2 operations in the definition.` The caller asked for an operation by the name it was built
   with, and it's gone. It fails at once (retrying won't make it appear), but every remediation is
   broken until one side changes. The safe way: add `remediate_config` *alongside* `remediate`.
   Put it back.
2. **Make the new field required.** In `models.py`, change `change_ticket: str | None = None` to
   `change_ticket: str`. Restart only the compliance worker (without `REQUIRE_TICKET`) and
   `force-check`: `config: Payload converter failed to decode Nexus operation input`. The old
   caller's request has no ticket, so the handler can't even read it. Run
   `test_old_caller_without_ticket_still_works`: it fails the same way. Put it back.

## Check yourself

1. Why can't you assume the caller and the handler run the same version of the contract?
2. You need to change `remediate`'s input in a way old callers can't send. What do you do?
3. Which error type does the handler raise for an unknown device, and why that one?
4. What's the difference between `OperationError(state=FAILED)` and `HandlerError(INTERNAL)` for
   the caller?
5. Where does the orchestrator's code handle a refused remediation, and what does an operator see?

<details>
<summary>Answers</summary>

1. Each team deploys on its own schedule. After either deploy there's a window, maybe a long one,
   where one side is new and the other old.
2. Add a new operation (`remediate_v2`) with the new input, keep `remediate` working, move callers
   over, and remove the old one when nothing calls it.
3. `HandlerError(type=BAD_REQUEST)`: the request can never work, so it fails straight away and
   isn't retried. No workflow starts.
4. Both reach the caller as a `NexusOperationError`. FAILED is final: no retries. INTERNAL is
   retried until it works or the caller's operation timeout runs out.
5. `run_child` catches `NexusOperationError` and returns `config: <the handler's message>` as the
   device's outcome. `status` shows it, and the next cycle tries again.

</details>

## Solution

[`solutions/day-24/`](../../../solutions/day-24/): `change_ticket` on `RemediationRequest` and
`OrchestratorInput` (`models.py`); the typed errors and ticket in `nexus/handler.py`; the
compatibility rules in `nexus/service.py`; the orchestrator passes the ticket on;
`starters/orchestrator.py` takes `--ticket`. Tests: three new ones in `tests/test_nexus.py`.
