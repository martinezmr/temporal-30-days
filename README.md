# 30 Days of Temporal (Python) — Network Automation Track

A self-paced, 30-day path from "I've run a few workflows" to a production-shaped
**`NetworkComplianceOrchestrator`**: a long-running entity workflow that compares
intent (Nautobot) with state (4 Arista cEOS nodes) and launches
`ConfigComplianceWorkflow` or `DeviceUpgradeWorkflow` when they drift — with Nexus
across team boundaries, AI where it helps, and workers ready for OpenShift + CI/CD.

Each day builds on the code from the day before, in this one repo.

## How to use it

1. Do the [lab setup](docs/lab-setup.md) once (about 30 minutes).
2. Each day, open that day's `README.md` and work through **Learn → Build → Break it → Done when**.
3. Write one line per day in [`LEARNING.md`](LEARNING.md): what surprised you.
4. Commit at the end of each day (`git commit -m "day 07: parallel backup"`), so you can diff your progress.

Budget 60–90 minutes a day. Weeks 1–2 move fast if you already know the basics.

## Where to run it

| Environment | Good for | Not good for |
| --- | --- | --- |
| **Your Mac** (Podman/OrbStack + containerlab + Nautobot) | Everything. This is the primary lab. | — |
| **GitHub Codespaces** ([details](docs/codespaces.md)) | Any day marked ☁️ below: Temporal server, UI, mocked device activities, Nexus, AI | Talking to your cEOS lab or Nautobot on your Mac |

## The 30 days

| Day | Topic | Key features | ☁️ Codespaces? |
| --- | --- | --- | --- |
| **Week 1 — Foundations, against real devices** | | | |
| [01](days/week-1/day-01-lab-up/README.md) | Lab up, repo tour | dev server, CLI, worker, task queues | ☁️ |
| [02](days/week-1/day-02-eapi-activity/README.md) | First real activity | activity timeouts, retry policy | local (or mock) |
| [03](days/week-1/day-03-models-and-failures/README.md) | Data models and failures | Pydantic converter, non-retryable errors | ☁️ with mock |
| [04](days/week-1/day-04-determinism/README.md) | Determinism | sandbox, replay, `workflow.now()` | ☁️ |
| [05](days/week-1/day-05-heartbeats-and-threads/README.md) | Blocking libs and heartbeats | thread-pool activities, heartbeats, cancellation | ☁️ with mock |
| [06](days/week-1/day-06-testing/README.md) | Testing | time-skipping env, mocks, Replayer | ☁️ |
| [07](days/week-1/day-07-parallel-backup/README.md) | Mini-project: parallel backup | `asyncio.gather`, partial failure | local |
| **Week 2 — Message passing and long-running workflows** | | | |
| [08](days/week-2/day-08-signals/README.md) | Signals | signal handlers, `wait_condition` | ☁️ |
| [09](days/week-2/day-09-queries/README.md) | Queries | query handlers | ☁️ |
| [10](days/week-2/day-10-updates/README.md) | Updates | validators, update-with-start, signal-with-start | ☁️ |
| [11](days/week-2/day-11-timers/README.md) | Timers and maintenance windows | durable timers, timeouts, time skipping | ☁️ |
| [12](days/week-2/day-12-continue-as-new/README.md) | Continue-As-New | history limits, `all_handlers_finished` | ☁️ |
| [13](days/week-2/day-13-entity-workflows/README.md) | Entity workflows | one workflow per device, request queue | ☁️ |
| [14](days/week-2/day-14-orchestrator-v0/README.md) | Mini-project: Orchestrator v0 | everything from Week 2 | local |
| **Week 3 — Composition and production hardening** | | | |
| [15](days/week-3/day-15-child-workflows/README.md) | Child workflows | parent close policy | ☁️ |
| [16](days/week-3/day-16-fan-out/README.md) | Fan-out without duplicates | ID conflict policy, concurrency caps | ☁️ |
| [17](days/week-3/day-17-saga-rollback/README.md) | Saga: safe config push | compensation, Arista config sessions | local |
| [18](days/week-3/day-18-schedules/README.md) | Schedules | overlap policy, backfill | ☁️ |
| [19](days/week-3/day-19-versioning/README.md) | Versioning (the CI/CD day) | patching, Worker Versioning | ☁️ |
| [20](days/week-3/day-20-observability/README.md) | Observability | search attributes, metadata, metrics, tracing | ☁️ |
| [21](days/week-3/day-21-production-workers/README.md) | Production-shaped workers | routing, rate limits, codecs, containers | local |
| **Week 4 — Nexus and AI** | | | |
| [22](days/week-4/day-22-nexus-sync/README.md) | First Nexus service | endpoints, sync operations | ☁️ |
| [23](days/week-4/day-23-nexus-async/README.md) | Async Nexus operations | workflow-backed operations, cancellation | ☁️ |
| [24](days/week-4/day-24-nexus-contracts/README.md) | Nexus errors and contracts | timeouts, errors, shared contract package | ☁️ |
| [25](days/week-4/day-25-llm-activity/README.md) | AI 1: LLM call as activity | structured output, retries | ☁️ |
| [26](days/week-4/day-26-durable-agent/README.md) | AI 2: durable agent | OpenAI Agents plugin, `activity_as_tool` | ☁️ with mock |
| [27](days/week-4/day-27-human-in-the-loop/README.md) | AI 3: human in the loop | approval updates, deadlines | ☁️ with mock |
| [28](days/week-4/day-28-mcp-guardrails/README.md) | AI 4: MCP and guardrails | MCP servers, allowlists, cost caps | ☁️ with mock |
| **Capstone** | | | |
| [29](days/capstone/day-29-assemble-orchestrator/README.md) | Assemble the orchestrator | all of it | local |
| [30](days/capstone/day-30-ocp-cicd/README.md) | Containers, CI/CD, OpenShift | Worker Versioning in a pipeline | local + CI |

## Architecture you are building toward

```
              Operators · nightly schedule · AI approvals
                         │ signals / queries / updates
┌──────────── namespace: default ─────────────┐     ┌──── namespace: compliance ────┐
│  NetworkComplianceOrchestrator (entity)     │────▶│  compliance-endpoint (Nexus)  │
│    ├─ DeviceUpgradeWorkflow (child)         │     │    └─ ConfigComplianceWorkflow │
│    └─ Troubleshooting agent (child)         │     │        (saga + rollback)       │
└──────┬───────────────┬──────────────┬───────┘     └──────────────┬────────────────┘
       │ intent        │ model calls  │ state                      │ config changes
   Nautobot         LLM API         4 × Arista cEOS ◀──────────────┘
```

## Repo layout

```
days/                 # one folder per day, each with a README
docs/                 # lab setup, Codespaces, feature checklist
lab/                  # containerlab topology, Temporal container script
src/netops_temporal/  # the code you grow all month
  activities/  workflows/  workers/  starters/  nexus/
tests/                # pytest + replay histories (tests/histories/)
.devcontainer/        # GitHub Codespaces: Temporal dev server + Python
.github/workflows/    # CI (grows into the Day 30 pipeline)
```

## Versions assumed

- Temporal Python SDK `temporalio` 1.34 (released 30 Sep 2026)
- Python 3.13 (3.14 works for Weeks 1–3; some AI libraries may lag)
- Temporal CLI dev server with `--db-filename` for persistence

See [docs/feature-checklist.md](docs/feature-checklist.md) for everything covered and what to explore after Day 30.
