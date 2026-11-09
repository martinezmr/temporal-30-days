# Week 2 — Talking to running workflows

**Goal:** by Friday you can build workflows that run for weeks, take orders while they run, answer
questions about themselves, wait for people and maintenance windows, and never outgrow their
history. The week ends with the first version of the compliance orchestrator.

The week builds one story:

1. A **watch** on one device (Days 8–10, 12): signals, queries, updates, continue-as-new.
2. A **change window** (Day 11): approval deadlines and maintenance windows with durable timers.
3. An **entity** per device (Day 13): one owner for every operation on a device.
4. The **orchestrator** (Day 14): all of it together, checking every device against intent and
   policy.

| Day | Topic | Temporal features |
| --- | --- | --- |
| [08](day-08-signals/README.md) | Signals: a workflow you can talk to | `@workflow.signal`, `wait_condition` |
| [09](day-09-queries/README.md) | Queries: ask a running workflow what it knows | `@workflow.query`, errors as state |
| [10](day-10-updates/README.md) | Updates, validators, start-if-missing | `@workflow.update`, validators, update-with-start, signal-with-start, `@workflow.init` |
| [11](day-11-timers/README.md) | Durable timers: deadlines and windows | `workflow.sleep`, `wait_condition(timeout=)`, `workflow.now()` |
| [12](day-12-continue-as-new/README.md) | Run forever without growing forever | `continue_as_new`, `all_handlers_finished` |
| [13](day-13-entity-workflows/README.md) | Entity workflows: one owner per device | async update handlers, `asyncio.Lock` |
| [14](day-14-orchestrator-v0/README.md) | Mini-project: NetworkComplianceOrchestrator v0 | everything above |

Every day works in mock mode (`LAB_MODE=mock`). With the lab, Days 8–14 talk to the real cEOS
nodes, and Day 14 also needs the course Nautobot.

**End-of-week checkpoint:** you can pick the right tool (signal, query, update, timer,
continue-as-new) for any interaction with a long-running workflow, and explain why.
