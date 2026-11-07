# Day 14 — Mini-project: Orchestrator v0

[← Day 13](../day-13-entity-workflows/README.md) · [Week 3 →](../../week-3/README.md)

## Goal

The first version of `NetworkComplianceOrchestrator`: detect and report drift, no remediation yet.

## Build

`workflows/orchestrator.py`, workflow ID `network-compliance-orchestrator`:

1. Every `interval` (default 15 min, timer), fetch intent for all devices from Nautobot and state from all 4 devices — activities, in parallel.
2. `compute_drift(intent, state) -> list[DriftReport]` — **an activity**, so diff logic can change freely without versioning the workflow.
3. Store the latest reports in state.
4. Handlers:
    - Query `get_drift() -> list[DriftReport]`
    - Signals `pause`, `resume`, `force_check`, `set_interval(minutes)`
5. Continue-as-new every 50 cycles or when suggested, carrying `OrchestratorState`.

Starter: `starters/orchestrator.py` uses `start_workflow(..., id_conflict_policy=USE_EXISTING)` so re-running it is safe.

## Break it

- Change an interface description on `bos-acc-01` by hand. Within one cycle (or right after `force_check`), `get_drift` shows it.
- Revert it. The drift clears on the next cycle.
- Restart everything (worker, Temporal container). The orchestrator carries on.

## Done when

- [ ] The orchestrator has run for at least 24 hours across at least one continue-as-new.
- [ ] Tests cover: drift detected, drift cleared, `force_check` short-circuits the timer (time-skipping).
