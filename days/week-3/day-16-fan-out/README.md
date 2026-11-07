# Day 16 — Fan-out without duplicates

[← Day 15](../day-15-child-workflows/README.md) · [Day 17 →](../day-17-saga-rollback/README.md)

## Goal

Detecting the same drift twice never starts two remediations, and you never remediate more than N devices at once.

## Learn

- Deterministic IDs (`compliance-bos-rtr-01`) + ID conflict policy: if a run with that ID is already open, `WorkflowIDConflictPolicy.USE_EXISTING` attaches instead of failing or duplicating. (From the orchestrator, simplest is to track open children in state; from outside clients, use the policy.)
- Children can report back to the parent with a signal: `workflow.get_external_workflow_handle(parent_id).signal(...)`.

## Build

1. Orchestrator state gets `in_flight: set[str]` and `pending: list[DriftReport]`.
2. Only start a child if the device isn't in `in_flight`, and only while `len(in_flight) < MAX_CONCURRENT_REMEDIATIONS` (2).
3. Children signal `remediation_finished(device, result)` to the parent (`workflow.info().parent.workflow_id`); the handler removes it from `in_flight`, and the loop starts the next pending one.
4. Carry `in_flight` and `pending` through continue-as-new.

## Break it

- Drift all 4 devices at once. Watch exactly 2 children run, then the next 2.
- Hit `force_check` 5 times quickly. Still one child per device.

## Done when

- [ ] Tests cover the concurrency cap and the no-duplicate rule.
