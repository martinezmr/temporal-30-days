# Day 29 — Assemble the orchestrator

[← Week 4](../../week-4/README.md) · [Day 30 →](../day-30-worker-versioning/README.md)

**Time:** 2 hours · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works); with the lab, today
**changes your cEOS devices** · **Solution:** [`solutions/day-29/`](../../../solutions/day-29/)

## Why today matters

You've built every piece this month: the orchestrator's cycle (Day 14), children and locks
(Days 15–16), the saga (Day 17), the compliance team's Nexus service (Days 22–24), the model's
explanation (Day 25), and approvals (Day 27). Today they run as one system. One piece is new: the
orchestrator holds a fix the model calls risky until an operator says yes.

Then you break it the way production does, killing workers in the middle of a cycle, and watch
it finish anyway.

Network analogy: your change process, automated end to end. Monitoring finds a deviation, an
engineer writes it up with a risk rating, low-risk standard changes go straight through, and
anything riskier waits for the CAB. Implementation follows the approved plan, with a rollback
plan attached.

## Concept

### The system, as the code has it

```
 operator: starters.orchestrator start | status | pending | approve | reject | force-check
     │ signals, queries, updates
     ▼
┌──────────────────── namespace: default ─────────────────────┐   ┌──────── namespace: compliance ─────────┐
│ NetworkComplianceOrchestrator          (netops-orchestration)│   │ ComplianceService     (compliance-tq)  │
│   every interval, for every device:                          │   │                                        │
│   1 fetch_device_intent, get_device_facts,                   │   │   get_policy (sync)                    │
│     check_config_compliance          (activities, device-io) │   │                                        │
│     get_policy ─────────────────────── Nexus ───────────────►│──►│                                        │
│   2 explain_drift: summary + risk    (activity, device-io)   │   │                                        │
│   3 config drift: risky? wait for `decide`                   │   │                                        │
│     remediate ──────────────────────── Nexus ───────────────►│──►│   remediate                            │
│   4 version drift: DeviceUpgradeWorkflow (child, ABANDON)    │   │     └► ConfigRemediationWorkflow       │
│   5 state, details, continue-as-new                          │   │         backup → push → verify         │
│                                                              │   │         (rollback if it doesn't)       │
└──────────────────────────┬───────────────────────────────────┘   └───────────────────┬────────────────────┘
                           │ intent, facts, config, model calls                         │ config changes
                     Nautobot · LLM server · 4 × cEOS ◄─────────────────────────────────┘
```

Two worker processes run it all:

| Worker | Namespace | Task queues | Runs |
| --- | --- | --- | --- |
| `workers.main` | `default` | `netops-orchestration`, `netops-device-io` | The orchestrator, upgrades, every other workflow; device and model activities |
| `workers.compliance` | `compliance` | `compliance-tq`, `netops-device-io` | The Nexus handlers, `ConfigRemediationWorkflow` and the saga's activities |

Two more workflows reuse the same pieces. The nightly `ComplianceAuditWorkflow` (Day 18) runs the
same check. `TroubleshootWorkflow` (Days 26–28) sends its approved fixes through the same
`remediate` operation.

The orchestrator still only decides. Every device change happens behind the Nexus endpoint or in
a child workflow, and every external call is an activity.

### The approval gate

| Explanation's risk | With `approval_risks=["medium", "high"]` |
| --- | --- |
| `low` | Fixed straight away, as before |
| `medium`, `high` | Waits for an operator's `decide` |
| none (the model was down) | Waits: nobody knows the risk |

A dry run changes nothing, so it never waits. The default is `approval_risks=[]`, which means no
gate. That's also what orchestrators started before today get when their input is read, so they
carry on exactly as before. No `patched` call is needed, because no new command runs unless the
list has something in it.

The wait has a deadline, `approval_wait_seconds` (15 minutes by default). The cycle finishes when
every device has been fixed, rejected, or run out of time. A device that ran out stays on the
`pending` list, and a decision sent between cycles counts on the next one.

## Walkthrough

### 1. `models.py`: decisions by device

```python
# file: netops_temporal/models.py
class DeviceDecision(Decision):
    """Day 29: an operator's answer about one device's config fix, sent to the orchestrator."""

    device: str


class PendingApproval(BaseModel):
    """Day 29: a config fix the orchestrator is holding until someone decides."""

    device: str
    missing_lines: list[str]
    risk: str
    summary: str = ""
```

`OrchestratorInput` gains `approval_risks` and `approval_wait_seconds`. It also gains `pending`
and `decisions`, which continue-as-new hands over like `state`, so a decision isn't lost when the
run changes.

### 2. `workflows/orchestrator.py`: the gate

```python
# file: netops_temporal/workflows/orchestrator.py
            if drift.kind == "config":
                ticket = self.change_ticket
                if self.needs_approval(state, dry_run):
                    decision = await self.approval(drift, state)
                    if decision is None:
                        risk = self.pending[drift.device].risk
                        return f"config: waiting for approval ({risk} risk)"
                    if not decision.approve:
                        return f"config: rejected by {decision.approver}"
                    # The approval is part of the change record (Day 24's REQUIRE_TICKET).
                    approved = f"approved by {decision.approver}"
                    ticket = f"{ticket}, {approved}" if ticket else approved
                async with self.remediation_slots:
```

The gate comes before the remediation slot (Day 16), so a fix waiting for a person doesn't hold
a slot another device could use. `approval()` is Day 27's wait:

```python
        try:
            await workflow.wait_condition(
                lambda: drift.device in self.decisions,
                timeout=timedelta(seconds=self.approval_wait_seconds),
            )
        except TimeoutError:
            return None
        del self.pending[drift.device]
        return self.decisions.pop(drift.device)
```

And Day 27's update, keyed by device:

```python
    @workflow.update
    def decide(self, decision: DeviceDecision) -> str:
        self.decisions[decision.device] = decision
        return "approved" if decision.approve else "rejected"

    @decide.validator
    def check_decision(self, decision: DeviceDecision) -> None:
        if decision.device not in self.pending or decision.device in self.decisions:
            raise ValueError(f"{decision.device} isn't waiting for approval")
```

The `pending_approvals` query lists what's waiting. When a device stops drifting, its pending
entry and any unused decision are dropped.

### 3. `starters/orchestrator.py`: four more words

`start --approve medium,high` turns the gate on. `pending` lists what's waiting, with the model's
summary and the lines. `approve <device>` and `reject <device>` send the update as `--as <name>`.

### 4. The tests

`tests/test_capstone.py` runs on a real dev server with both namespaces (`nexus_env`, Day 22):

- `test_high_risk_waits_for_approval`: nyc-acc-01 (wrong version *and* a missing line, so the
  model says `high`):
  - It waits, and nothing is pushed: the only Nexus operation so far is `get_policy`.
  - A decision for a device that isn't waiting is refused.
  - After bob approves, the line is pushed and the upgrade child starts.
- `test_rejected_change_is_not_pushed`.
- `test_unanswered_approval_keeps_waiting_next_cycle`: with `approval_wait_seconds=1`, the
  outcome is `waiting for approval (medium risk)`, and a decision sent afterwards is applied on
  the next cycle.
- `test_full_cycle_converges_config_drift`: all four devices wait, all are approved, and the
  second cycle finds no config drift. nyc-acc-01's version drift is left to its upgrade.

`tests/histories/orchestrator_cycle.json` is the history of a two-cycle run from the mock lab,
with five decisions in it. Day 6's replay test replays it on every run. Remove the gate's
`timeout=` and the replay fails with `TMPRL1100 Nondeterminism error`, which is the protection
Day 30 depends on.

## Run it

### In mock mode

Start both workers (Day 23) with `LAB_MODE=mock` and the orchestrator with the gate on:

```bash
uv run --env-file .env python -m netops_temporal.starters.orchestrator start --apply --approve medium,high
uv run --env-file .env python -m netops_temporal.starters.orchestrator pending
```

```
bos-rtr-01 [medium risk] bos-rtr-01 is missing 2 line(s) the compliance policy requires.
    ntp server 192.0.2.10
    logging host 192.0.2.50
bos-acc-01 [medium risk] bos-acc-01 is missing 1 line(s) the compliance policy requires.
    ntp server 192.0.2.10
nyc-rtr-01 [medium risk] nyc-rtr-01 is missing 2 line(s) the compliance policy requires.
    ...
nyc-acc-01 [high risk] nyc-acc-01 runs a different EOS version from its intent.
    ntp server 192.0.2.10
```

Approve three and reject one (`approve bos-rtr-01 --as bob`, ..., `reject nyc-rtr-01 --as bob`),
then `status`:

```
after 1 cycle(s):
  bos-acc-01  drifted   config: 1 missing (want 1 policy line(s) present)
                        [medium risk] bos-acc-01 is missing 1 line(s) ...
                        -> config: pushed 1 line(s)
  ...
  nyc-acc-01  drifted   version: 4.32.0F (want 4.33.1F); config: 1 missing ...
                        -> upgrade: started upgrade-nyc-acc-01; config: pushed 1 line(s)
  nyc-rtr-01  drifted   config: 2 missing (want 2 policy line(s) present)
                        -> config: rejected by bob
```

`force-check`: the second cycle shows the fixed devices as `compliant`, and nyc-rtr-01 waiting
again. Rejecting a fix doesn't make the drift go away. Change the intent or the policy for that.

In the UI, the orchestrator's history has a **WorkflowExecutionUpdateAccepted** per decision
(bob's name in the input), a `remediate` Nexus operation for each approved device and none for
the rejected one. In the `compliance` namespace, each remediation shows `Change ticket: approved
by bob` in its details.

### Against the lab

This changes your cEOS devices. Restart both workers without `LAB_MODE=mock`, with your model
server (Day 25) running. Terminate the old orchestrator and start it again the same way. The
first cycle takes longer: real devices, and a real model writing each explanation. The risk
ratings are now the model's own. In testing, `qwen2.5:7b` rated nyc-rtr-01's two missing lines
`high` and bos-rtr-01's identical two `medium`. That's the case for a deterministic gate and a
human, rather than trusting the label.

DeviceUpgradeWorkflow is Day 15's stand-in (cEOS can't be upgraded in place), so it ends with
`still on 4.32.0F` and the next cycle starts another one.

To put the lab back afterwards (later days expect the original drift), roll back each device's
last commit, as on Day 17:

```bash
for d in bos-acc-01 bos-rtr-01 nyc-rtr-01 nyc-acc-01; do
  uv run --env-file .env python -c "from netops_temporal.devices import config_push; config_push.rollback('$d')"
done
```

## Break it

Do these in order, on one run, with the lab or the mock.

1. **Kill the compliance worker, then approve.** `kill -9` the `workers.compliance` process and
   approve bos-acc-01. The update is accepted (the orchestrator's worker is fine), but nothing
   starts in `compliance`. `temporal workflow describe -w orchestrator` lists the `remediate`
   operation as pending, scheduled, with `upstream timeout`: the handler isn't there to start the
   workflow. Start the worker again. Within seconds the remediation runs and the status says
   `pushed 1 line(s)`.
2. **Kill the main worker mid-cycle.** Approve the rest so the cycle can finish, then
   `force-check` and, a second later, `kill -9` the `workers.main` process. `describe` shows
   which activity was cut off. Against the lab, the model is usually still writing an
   explanation (`explain_drift`, state STARTED, attempt 1). Start the worker again. Once the
   activity's timeout expires (a minute), attempt 2 runs and the cycle finishes. In the history,
   that activity's started event says `attempt 2` with `activity StartToClose timeout`. Nothing
   that had already finished ran again.
3. **Nobody answers.** Run `test_unanswered_approval_keeps_waiting_next_cycle`, which starts an
   orchestrator with `approval_wait_seconds=1` and doesn't decide. The cycle finishes with
   `waiting for approval (medium risk)`, `pending` still lists the device, and a late approval
   is applied on the next cycle.

## Check yourself

1. Which worker would you restart if remediations stopped but cycles kept running? And the other
   way round?
2. Why does the approval gate need no `patched` call, when Day 25's explanation did?
3. Why does a fix wait for approval *before* taking a remediation slot?
4. What happens to a decision sent while the orchestrator is between cycles, or continuing as new?
5. A model rates a two-line change `high` on one router and `medium` on its twin. What in today's
   design keeps that from mattering?

<details>
<summary>Answers</summary>

1. Remediations: `workers.compliance`, which runs the Nexus handlers, the remediation workflow
   and its activities. Cycles: `workers.main`, which runs the orchestrator and the collection and
   explanation activities.
2. Day 25 added an activity every run would schedule, so old histories would see a command they
   never had. The gate adds commands only when `approval_risks` isn't empty, and orchestrators
   started before today read it as `[]`.
3. Slots limit how many devices are changed at once (Day 16). A fix waiting for a person isn't
   changing anything, so it shouldn't stop another device's approved fix from running.
4. It's kept in `decisions` (handed over by continue-as-new) and used as soon as that device
   reaches the gate on the next cycle.
5. The rating only decides *whether a person looks*. With `medium` and `high` both gated, both
   wait. And whatever is approved goes through the same saga, which verifies and rolls back.

</details>

## Solution

[`solutions/day-29/`](../../../solutions/day-29/): `DeviceDecision`, `PendingApproval`, and
`approval_risks`, `approval_wait_seconds`, `pending` and `decisions` on `OrchestratorInput` in
`models.py`; `needs_approval`, `approval`, the `decide` update and validator, and the
`pending_approvals` query in `workflows/orchestrator.py`; `--approve`, `pending`, `approve` and
`reject` in `starters/orchestrator.py`. Tests: new `tests/test_capstone.py` and
`tests/histories/orchestrator_cycle.json`.
