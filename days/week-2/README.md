# Week 2 — Message passing and long-running workflows

**Goal:** a workflow that runs for weeks, takes commands while running, reports status on demand, and never outgrows its history. This is the core of the orchestrator.

| Message | Direction | Returns a value? | Can change state? | Network use |
| --- | --- | --- | --- | --- |
| Signal | In, fire-and-forget | No | Yes | "Pause checks", "force re-check now" |
| Query | Out, read-only | Yes | No | "What is drifted right now?" |
| Update | In, request-response, validated | Yes | Yes | "Approve this remediation" |

Docs for Days 8–10: [Workflow message passing](https://docs.temporal.io/develop/python/workflows/message-passing)

| Day | Topic |
| --- | --- |
| [08](day-08-signals/README.md) | Signals |
| [09](day-09-queries/README.md) | Queries |
| [10](day-10-updates/README.md) | Updates and validators |
| [11](day-11-timers/README.md) | Durable timers and maintenance windows |
| [12](day-12-continue-as-new/README.md) | Continue-As-New |
| [13](day-13-entity-workflows/README.md) | The entity workflow pattern |
| [14](day-14-orchestrator-v0/README.md) | Mini-project: Orchestrator v0 |
