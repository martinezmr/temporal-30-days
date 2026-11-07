# Day 27 — AI pattern 3: human in the loop

[← Day 26](../day-26-durable-agent/README.md) · [Day 28 →](../day-28-mcp-guardrails/README.md)

## Goal

The agent may *propose* a change; only a human approval lets a deterministic workflow apply it.

## Build

`ProposedRemediationWorkflow`:

1. Agent (Day 26) returns a structured `Proposal(device, lines, reasoning)`.
2. `stage_config` + `get_session_diff` (Day 17) — store the **real device diff**, not the model's description of it.
3. Wait for a decision, with a deadline:

    ```python
    @workflow.update
    async def decide(self, d: Decision) -> str:
        self.decision = d
        return "recorded"

    @decide.validator
    def check(self, d: Decision) -> None:
        if self.decision is not None:
            raise ValueError("already decided")
        if d.approver not in APPROVERS:
            raise ValueError("not an approver")

    try:
        await workflow.wait_condition(lambda: self.decision is not None, timeout=timedelta(hours=4))
    except asyncio.TimeoutError:
        self.decision = Decision(approved=False, approver="timeout")
    ```

4. Approved → Nexus `remediate` (commit, verify, rollback). Rejected or timed out → `abort_session`.
5. A query `get_proposal()` so an approver (or a future UI/Slack bot) can see reasoning + real diff.

## Optional

[Workflow Streams](https://docs.temporal.io/develop/python/workflows/workflow-streams) (Public Preview) to stream the agent's progress to a UI.

## Done when

- [ ] No path exists from the model to a committed config without a recorded human approval in history.
