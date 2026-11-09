# Week 3 — From reporting drift to fixing it, safely

**Goal:** by Friday the orchestrator fixes config drift on real devices, rolls back anything that
doesn't verify, never touches one device twice at once, runs a nightly audit you can pause, and
you can change its code while it's running. You can find any change by device, and the workers
look like something you'd run in production: split by job, gentle on devices, encrypted, and in a
container.

The week builds on Day 14's orchestrator:

1. **Act on drift** (Days 15–17): a child workflow per drift, the workflow ID as a lock, a cap on
   how many run at once, and a saga that undoes a push if it doesn't verify.
2. **Run it for real** (Days 18–19): a nightly audit as a schedule, and changing workflow code
   while runs are in flight.
3. **Operate it** (Days 20–21): find workflows by device, see what they're doing, measure the
   workers, then split and harden them.

| Day | Topic | Temporal features |
| --- | --- | --- |
| [15](day-15-child-workflows/README.md) | Child workflows and parent close policies | `execute_child_workflow`, `start_child_workflow`, `ParentClosePolicy` |
| [16](day-16-fan-out/README.md) | Workflow IDs as locks, and bounded fan-out | ID conflict and reuse policies, `WorkflowAlreadyStartedError`, `asyncio.Semaphore` |
| [17](day-17-saga-rollback/README.md) | Saga: a config push that undoes itself | compensations, cancellation inside activities, NAPALM commit and rollback |
| [18](day-18-schedules/README.md) | Schedules: a nightly audit you can pause and replay | `create_schedule`, overlap policies, trigger, backfill, pause notes |
| [19](day-19-versioning/README.md) | Changing a workflow while it's running | `workflow.patched`, `deprecate_patch`, replay tests |
| [20](day-20-observability/README.md) | Observability: "what happened to bos-acc-01?" | search attributes, summaries, current details, Prometheus metrics, OpenTelemetry |
| [21](day-21-production-workers/README.md) | Production-shaped workers, on your laptop | task queue routing, rate limits, graceful shutdown, payload codecs, codec server |

Every day works in mock mode (`LAB_MODE=mock`). With the lab, Day 17 **changes your cEOS
devices** (it shows how to roll them back afterwards), and Days 15–20 also need the course
Nautobot for the orchestrator. Days 18, 20 and 21 use a few more things from your machine: the
Temporal CLI for schedules, the search attributes `lab/start-temporal.sh` registers, and
(optionally) podman or docker for the worker container.

After pulling Week 3, run `uv sync`: Days 20 and 21 add `temporalio[opentelemetry]`,
`opentelemetry-sdk` and `aiohttp`.

**End-of-week checkpoint:** you can explain, for a change pushed by the orchestrator, how it was
prevented from running twice, what undoes it if it fails, how you'd find it next month, and how
you'd deploy a new version of the code without breaking the remediations in flight.
