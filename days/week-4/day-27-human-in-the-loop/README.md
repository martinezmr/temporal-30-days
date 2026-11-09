# Day 27 — Human in the loop: the agent proposes, you decide

[← Day 26](../day-26-durable-agent/README.md) · [Day 28 →](../day-28-mcp-guardrails/README.md)

**Time:** 75 minutes · **Needs the cEOS lab?** No (`LAB_MODE=mock`) · **Solution:** [`solutions/day-27/`](../../../solutions/day-27/)

## Why today matters

Yesterday's agent can propose a fix, and nothing more. That's deliberate. During testing, a
small model looking at a flapping OSPF neighbour proposed `no ip ospf area 0.0.0.0`, which would
have taken the link out of OSPF altogether. Another wrapped its fix in `configure terminal` and
`end`, as if it were typing into a console.

So a change needs a person's approval, and the person must not be the one who asked: the
four-eyes rule your change process already has. Approval can take minutes or hours, and the
workflow has to wait for it without holding anything open, remember who approved what, and give
up cleanly if nobody answers.

Network analogy: the change advisory board. The engineer writes the change, someone else
approves it, and the implementation follows the approved plan exactly, not whatever the engineer
feels like typing on the night.

## Concept

### Propose, decide, apply: three different actors

| Step | Who | How |
| --- | --- | --- |
| Propose | The agent | `propose_change` writes lines into the run's context (Day 26) |
| Decide | A person who isn't the requester | The `decide` **update**, checked by a **validator** |
| Apply | Deterministic code | The compliance team's `remediate` operation (Day 23): Day 17's saga, Day 16's lock, Day 24's rules |

The agent never gets near the push. Its tools still can't change anything. After the decision,
plain workflow code passes exactly the approved lines to the same remediation every other config
change goes through.

### An update with a validator

Day 11 used signals for approval. Today's `decide` is an **update**, for two reasons:

- **The caller gets an answer.** `execute_update` returns "approved" or "rejected", or raises if
  the decision was refused. A signal is fire-and-forget: you never know whether it counted.
- **Bad decisions never enter the history.** The validator runs first. If it raises (approving
  your own request, deciding twice, no approver), the update is rejected, and the history has no
  trace of it. Only accepted decisions are recorded, as **WorkflowExecutionUpdateAccepted** and
  **Completed** events, with the approver's name in the input. That's your audit trail.

```python
@decide.validator
def check_decision(self, decision: Decision) -> None:
    if self._stage != "awaiting_approval":
        raise ValueError(f"not awaiting approval (stage: {self._stage})")
    ...
    if decision.approver == self._requested_by:
        raise ValueError("you can't approve your own request")
```

A validator must not change the workflow's state: it only says yes or no.

### Waiting, with a deadline

`wait_condition(..., timeout=30 minutes)` is Day 11's pattern. The timer lives on the server, so
it fires even if no worker is running. No decision in time means no change.

### A known limit: what the saga can verify

Day 17's saga verifies a push by checking that every pushed line now appears in the running
config. That suits policy lines like `ntp server 192.0.2.10`. On a real device, a negation like
`no shutdown` never shows up in the running config, so the saga would report it as not verified
and roll it back. (The mock lab shows pushed lines as they are, so it won't show you this.) That's the safe failure: nothing stays half-applied. It does mean today's approval flow is
for adding config. Verifying arbitrary changes needs a smarter check, such as comparing the
interface state before and after.

## Walkthrough

### 1. `models.py`: who asked, and who decided

```python
# file: netops_temporal/models.py
class TroubleshootRequest(BaseModel):
    device: str
    symptom: str
    # Day 27: who asked (they can't approve their own change), and how long to wait for
    # someone else to.
    requested_by: str = ""
    approval_timeout_minutes: int = 30


class Decision(BaseModel):
    """Day 27: a human's answer to the agent's proposal."""

    approve: bool
    approver: str
    comment: str = ""
```

`TroubleshootReport` gains `outcome` (what happened to the proposal) and `remediation` (the
saga's result, if it ran).

### 2. `workflows/troubleshoot.py`: wait, decide, apply

After the agent finishes, mode commands (`configure terminal`, `end`, `write memory`, ...) are
removed from the proposal: the saga runs its own config session. If anything is left:

```python
# file: netops_temporal/workflows/troubleshoot.py
        self._stage = "awaiting_approval"
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=timedelta(minutes=req.approval_timeout_minutes),
            )
        except TimeoutError:
            self._stage = "done"
            report.outcome = "approval timed out: nothing changed"
            return report
```

On approval, `apply` calls `ComplianceService.remediate` with `dry_run=False`, the approved lines,
and `change_ticket=f"approved by {decision.approver}"`, so Day 24's `REQUIRE_TICKET` rule accepts
it. A remediation already running for the device fails the operation (Day 16's lock), and the
outcome says so.

```python
    @workflow.update
    def decide(self, decision: Decision) -> str:
        self._decision = decision
        self._stage = "decided"
        return "approved" if decision.approve else "rejected"
```

Two queries, `stage()` and `proposal()`, let the starter (or the UI) see what's waiting.

### 3. `starters/troubleshoot.py`: ask, approve, reject

`ask` starts the workflow, waits until the agent is done, and prints the proposal and the
workflow ID. `approve` and `reject` send the update as `--as <name>` (default: your login), print
the answer, and wait for the outcome. `report` prints a finished report.

### 4. The tests

In `tests/test_troubleshoot.py`, a scripted model proposes `ntp server 192.0.2.10`, and alice
asks:

- `test_approved_proposal_runs_remediation`: bob approves, the line is pushed (mock state), and
  the history shows the `remediate` Nexus operation.
- `test_self_approval_rejected_by_validator`: alice can't approve, and the workflow is still
  waiting afterwards.
- `test_second_decision_rejected`: while bob's approval is being applied, carol's decision is
  refused: `not awaiting approval`.
- `test_rejected_proposal_changes_nothing` and `test_no_decision_times_out_without_change`
  (the test server skips the 30 minutes).
- `test_mode_commands_stripped_from_proposal`.

## Run it

Start the main worker and the compliance worker (Day 23). With Ollama, ask something the agent
can fix by adding config:

```bash
uv run --env-file .env python -m netops_temporal.starters.troubleshoot ask bos-acc-01 \
    "The compliance audit says bos-acc-01 is missing the NTP server 192.0.2.10. Check the running config and propose the fix." \
    --as alice
```

```
Proposed change, waiting for someone else's approval:
  ntp server 192.0.2.10
because: Add NTP server 192.0.2.10 to ensure the device is in compliance with the audit.

approve or reject troubleshoot-bos-acc-01-9e95bd (as someone other than alice)
```

(In mock mode the scripted model never proposes anything: to see the approval flow without a
model server, run the tests above.) Then approve as someone else:

```bash
uv run --env-file .env python -m netops_temporal.starters.troubleshoot approve troubleshoot-bos-acc-01-9e95bd --as bob
```

`outcome: approved by bob: pushed 1 line(s)`. In the UI, the history has
**WorkflowExecutionUpdateAccepted** with bob's decision, the `remediate` Nexus operation, and in
the `compliance` namespace, the remediation workflow with `Change ticket: approved by bob` in its
details.

## Break it

1. **Approve as yourself.** `approve <id> --as alice`:
   `decision refused: ValueError: you can't approve your own request`. Look at the history:
   there's no event for it. The validator turned it away before anything was written.
2. **Approve twice.** After bob's approval, `approve <id> --as carol`. If the change is still
   being applied, the validator refuses it (`not awaiting approval (stage: applying)`). Once the
   workflow has finished, the server refuses it (`workflow execution already completed`).
   Either way, one decision counts.
3. **Let it time out.** `ask` again, then don't answer. To avoid waiting 30 minutes, run
   `test_no_decision_times_out_without_change`: the outcome is
   `approval timed out: nothing changed`, and nothing was pushed.

## Check yourself

1. Why is the decision an update and not a signal?
2. What's a validator allowed to do, and what not?
3. Where does the approved change get applied, and why not by the agent?
4. What happens if nobody decides?
5. Why would an approved `no shutdown` be rolled back?

<details>
<summary>Answers</summary>

1. The caller learns whether the decision was accepted, and refused decisions never enter the
   history. A signal is always recorded, and the sender never hears back.
2. Read the workflow's state and raise to reject. It must not change state or do anything
   non-deterministic.
3. In the compliance team's `remediate` operation: the saga, with its lock, verification and
   rollback. The agent only proposes; plain workflow code passes on exactly what a person
   approved.
4. After `approval_timeout_minutes` the workflow returns with `approval timed out: nothing
   changed`. The timer is on the server, so it fires even if no worker is running.
5. The saga verifies by looking for each pushed line in the running config, and `no shutdown`
   never appears there. Unverified means rolled back: safe, if not what you wanted.

</details>

## Solution

[`solutions/day-27/`](../../../solutions/day-27/): `Decision`, `requested_by`,
`approval_timeout_minutes`, `outcome` and `remediation` in `models.py`; the approval wait, the
`decide` update and validator, and `apply` in `workflows/troubleshoot.py`; `ask`, `approve`,
`reject` and `report` in `starters/troubleshoot.py`. Tests: six new ones in
`tests/test_troubleshoot.py`.
