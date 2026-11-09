# 30 Days of Temporal for Network Automation Engineers

A self-paced course that teaches [Temporal](https://temporal.io) (Python SDK) to network
automation engineers who already write Python but are new to Temporal. You build real
workflows against a local lab of Arista cEOS devices and Nautobot. By Day 30 you'll have used
every major Temporal feature and know when each one is the right tool for a network job.

## Who this is for

- You write Python scripts comfortably (functions, classes, `requests`/Netmiko-style automation).
- You know EOS, `show` commands, config changes, and what a source of truth is for.
- You're new to Temporal: workflows, activities, workers, replay, signals, and so on. That's
  what the course explains, from the ground up.

No async primer, no Python basics. Every Temporal idea is explained in plain words with a
network analogy before you write code for it.

## What you'll build

Over the month you grow one codebase in `src/netops_temporal/` into a
**`NetworkComplianceOrchestrator`**: a long-running workflow that compares intent (Nautobot)
with state (4 cEOS nodes) and launches compliance or upgrade workflows when they drift. Along
the way you'll use three device libraries, each where it fits best:

| Library | First used | Why there |
| --- | --- | --- |
| **pyeapi** | Day 2 | Structured JSON from eAPI, so you can focus on Temporal itself |
| **Netmiko** | Day 5 | Slow, blocking SSH sessions: perfect for learning heartbeats and cancellation |
| **NAPALM** | Day 7 | Normalized backups, then candidate/commit/rollback for the Day 17 safe-change saga |
| **pynautobot** | Day 7 | Reads intent from Nautobot |

## The lab (all local)

| Piece | How |
| --- | --- |
| Temporal dev server + UI | `./lab/start-temporal.sh` → http://localhost:8233 |
| 4 × Arista cEOS (containerlab) | `lab/ceos-clab.clab.yml`, static IPs, eAPI + SSH as `admin`/`admin` |
| Nautobot | `lab/nautobot/start.sh` + `lab/nautobot/seed.py` → http://localhost:8080 |
| A language model (Days 25–28, optional) | Ollama on your laptop, or any OpenAI-compatible server |

Set it up once with [docs/lab-setup.md](docs/lab-setup.md) (30–45 minutes). Behind a jump host?
`lab/tunnels.sh` handles it.

**No lab handy?** Every day also runs in **mock mode** (`LAB_MODE=mock`): device and Nautobot
calls replay outputs recorded from the real lab, a scripted model stands in on the AI days, and
you can fake failures (a device down, bad credentials, slow CLI). Temporal itself is always real.

## How this course works

1. Do the [lab setup](docs/lab-setup.md) once.
2. Each day, open that day's `README.md`. Every lesson has the same sections:
   - **Why today matters**: the network problem.
   - **Concept**: the Temporal idea, explained before any code.
   - **Walkthrough**: the code, built step by step, every new line explained.
   - **Run it**: exact commands and the output you should see.
   - **Break it**: deliberate failures to watch Temporal handle.
   - **Check yourself**: questions, with answers you can expand.
3. Write the code yourself in `src/netops_temporal/`. If you get stuck, compare with that day's
   solution.
4. Write one line a day in [`LEARNING.md`](LEARNING.md): what surprised you.
5. Work on your own branch (`git switch -c my-progress`) and commit at the end of each day
   (`git commit -am "day 02: first activity"`). Keep `main` as published: CI there checks that
   `src/` still matches the Day 1 starting point.

Budget 60–90 minutes a day.

## Using the solutions

`solutions/day-NN/` holds the **complete working code as it should look at the end of Day NN**,
with tests. Day 1's solution is exactly the `src/` you start with. Each later solution is the
previous one plus that day's work.

```bash
# What's different between my code and the Day 2 solution?
diff -r -x __pycache__ src/netops_temporal solutions/day-02/netops_temporal

# Run the Day 2 solution instead of my code (worker, starter, anything):
scripts/solution.sh 02 python -m netops_temporal.workers.main
scripts/solution.sh 02 python -m netops_temporal.starters.facts bos-rtr-01

# Run a solution's tests (mock mode, no lab needed):
scripts/test-solutions.sh 02

# Fell behind? Start the next day from a known-good copy:
rm -rf src/netops_temporal && cp -r solutions/day-02/netops_temporal src/
```

`scripts/solution.sh` puts the solution folder first on `PYTHONPATH`, so
`import netops_temporal` loads the solution, not your `src/`. It loads `.env` if you have one.

## The 30 days

**Needs the lab?** says what each day needs from your cEOS lab. **Optional** means the day runs in
mock mode too. **No** means you don't need it at all.

| Day | Topic | Key features | Needs the lab? |
| --- | --- | --- | --- |
| **Week 1 — Foundations, against real devices** | | | |
| [01](days/week-1/day-01-lab-up/README.md) | Lab up, how Temporal runs your code | server, worker, task queues, event history | No |
| [02](days/week-1/day-02-eapi-activity/README.md) | First real activity with pyeapi | sync activities, timeouts, retry policy | Optional |
| [03](days/week-1/day-03-models-and-failures/README.md) | Data models and failures | Pydantic converter, non-retryable errors | Optional |
| [04](days/week-1/day-04-determinism/README.md) | Determinism and replay | sandbox, replay, `workflow.now()` | No |
| [05](days/week-1/day-05-heartbeats-and-threads/README.md) | Netmiko, heartbeats, cancellation | thread-pool activities, heartbeats, cancellation | Optional |
| [06](days/week-1/day-06-testing/README.md) | Testing | time-skipping env, stubbed activities, Replayer | No |
| [07](days/week-1/day-07-parallel-backup/README.md) | Mini-project: parallel backup (NAPALM) + intent (Nautobot) | `asyncio.gather`, partial failure | Optional |
| **Week 2 — Message passing and long-running workflows** | | | |
| [08](days/week-2/day-08-signals/README.md) | Signals | signal handlers, `wait_condition` | Optional |
| [09](days/week-2/day-09-queries/README.md) | Queries | query handlers | Optional |
| [10](days/week-2/day-10-updates/README.md) | Updates | validators, update-with-start, signal-with-start | Optional |
| [11](days/week-2/day-11-timers/README.md) | Timers and maintenance windows | durable timers, timeouts, time skipping | Optional |
| [12](days/week-2/day-12-continue-as-new/README.md) | Continue-As-New | history limits, `all_handlers_finished` | Optional |
| [13](days/week-2/day-13-entity-workflows/README.md) | Entity workflows | one workflow per device, request queue | Optional |
| [14](days/week-2/day-14-orchestrator-v0/README.md) | Mini-project: Orchestrator v0 | everything from Week 2 | Optional |
| **Week 3 — Composition and production hardening** | | | |
| [15](days/week-3/day-15-child-workflows/README.md) | Child workflows | parent close policy | Optional |
| [16](days/week-3/day-16-fan-out/README.md) | Fan-out without duplicates | ID conflict policy, concurrency caps | Optional |
| [17](days/week-3/day-17-saga-rollback/README.md) | Saga: safe config push (NAPALM) | compensation, candidate/commit/rollback | Optional (changes your devices) |
| [18](days/week-3/day-18-schedules/README.md) | Schedules | overlap policy, backfill | Optional |
| [19](days/week-3/day-19-versioning/README.md) | Versioning | patching, Worker Versioning | Optional |
| [20](days/week-3/day-20-observability/README.md) | Observability | search attributes, metadata, metrics, tracing | Optional |
| [21](days/week-3/day-21-production-workers/README.md) | Production-shaped workers, locally | task-queue routing, rate limits, graceful shutdown, codecs | Optional |
| **Week 4 — Nexus and AI** | | | |
| [22](days/week-4/day-22-nexus-sync/README.md) | First Nexus service | endpoints, sync operations | Optional |
| [23](days/week-4/day-23-nexus-async/README.md) | Async Nexus operations | workflow-backed operations, cancellation | Optional |
| [24](days/week-4/day-24-nexus-contracts/README.md) | Nexus errors and contracts | timeouts, errors, shared contract package | No |
| [25](days/week-4/day-25-llm-activity/README.md) | AI 1: LLM call as an activity (any OpenAI-compatible API) | structured output, retries | No |
| [26](days/week-4/day-26-durable-agent/README.md) | AI 2: durable agent | agents as workflows, tools as activities | Optional |
| [27](days/week-4/day-27-human-in-the-loop/README.md) | AI 3: human in the loop | approval updates, deadlines | No |
| [28](days/week-4/day-28-mcp-guardrails/README.md) | AI 4: MCP and guardrails | MCP servers, allowlists, guardrails | No |
| **Capstone** | | | |
| [29](days/capstone/day-29-assemble-orchestrator/README.md) | Assemble the orchestrator | all of it | Optional (changes your devices) |
| [30](days/capstone/day-30-worker-versioning/README.md) | Worker Versioning locally + CI | v1 and v2 workers side by side, pinned and auto-upgrade, ramping, replay tests in CI | No |

## Architecture you're building toward

```
              Operators · nightly schedule · AI approvals
                         │ signals / queries / updates
┌──────────── namespace: default ─────────────┐     ┌──── namespace: compliance ──────┐
│  NetworkComplianceOrchestrator (entity)     │────▶│  compliance-endpoint (Nexus)    │
│    └─ DeviceUpgradeWorkflow (child)         │     │    └─ ConfigRemediationWorkflow │
│  TroubleshootWorkflow (agent)               │────▶│        (saga + rollback)        │
└──────┬───────────────┬──────────────┬───────┘     └──────────────┬──────────────────┘
       │ intent        │ model calls  │ state                      │ config changes
   Nautobot      an OpenAI-compatible  4 × Arista cEOS ◀───────────┘
                 model server
```

## Repo layout

```
days/                 # one folder per day, each with a README (the lesson)
solutions/day-NN/     # complete code + tests as of the end of each day
src/netops_temporal/  # YOUR code, grown all month (starts equal to solutions/day-01)
  activities/  workflows/  workers/  starters/   # Temporal code
  devices/  mock/  fixtures/  tools/             # lab helpers, mock mode, check_lab
tests/                # tests for your code
lab/                  # Temporal, containerlab topology, Nautobot, jump-host tunnels
scripts/              # solution.sh, test-solutions.sh, check_lessons.py
docs/                 # lab setup, Codespaces, feature checklist
```

## Versions

- Python 3.13, managed with [`uv`](https://docs.astral.sh/uv/)
- Temporal Python SDK `temporalio` ≥ 1.34 (tested with 1.35)
- Temporal CLI dev server (with `--db-filename` for persistence)
- Arista cEOS 4.32.0F, Nautobot 3.2.8

See [docs/feature-checklist.md](docs/feature-checklist.md) for everything covered and what to
explore after Day 30.
