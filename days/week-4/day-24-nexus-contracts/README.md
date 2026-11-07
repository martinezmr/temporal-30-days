# Day 24 — Nexus errors, timeouts and contracts

[← Day 23](../day-23-nexus-async/README.md) · [Day 25 →](../day-25-llm-activity/README.md)

## Goal

Treat the Nexus contract like a public API: versioned, typed, with defined failure behaviour.

## Learn

- `schedule_to_close_timeout` on each operation call bounds the whole operation.
- Handler failures surface in the caller as `NexusOperationError` wrapping the cause. Raise non-retryable errors (e.g. `nexusrpc.HandlerError` with a non-retryable type, or `ApplicationError(non_retryable=True)` from the workflow) for "this will never work" cases.
- Contracts evolve like APIs: add optional fields, never rename or remove; add a new operation for breaking changes.

## Build

1. Move `nexus/compliance_service.py` and its models into a tiny package `netops_contracts/` with its own version. Both workers import it.
2. Make `remediate` reject devices outside an allowlist with a non-retryable error. Handle it in the orchestrator by marking the device `ComplianceState="manual"`.
3. Add a 2-hour `schedule_to_close_timeout` to `remediate`; on timeout, alert (log + search attribute).

## Design note

In production this is how an inventory, security or change-management team can expose "get device intent" or "open a change ticket" to your orchestrator without sharing a namespace, a repo, or a deploy schedule.

## Done when

- [ ] Tests cover: success, non-retryable rejection, timeout.
