# Design: Rewrite "30 Days of Temporal" for network automation engineers

Date: 2026-11-07 · Status: reviewed; awaiting author approval

## Intent and why

The repo is meant to teach Temporal (Python SDK) in 30 days to network automation
engineers, but in its current form it is an outline, not a course:

- Each day is ~50 lines. "Learn" is a list of definitions that does not explain the
  "Build" steps.
- **No solutions exist.** `src/` contains only the Day 1 hello-world.
- Snippets call helpers that are never defined (Day 2's `run_commands`, `DEVICE_HOSTS[...]`).
  `DEVICE_HOSTS` is a comma string in `.env.example` that nothing parses.
- Libraries switch without explanation: Day 2 says "niquests + runCmds", Day 5 uses
  `pyeapi`, which is not even a dependency.

The author (and their team) is adopting Temporal as the network automation team's
orchestration tool. The author wants to know **all of Temporal's features and
capabilities** and wants a course that **other network automation engineers who are
good at Python but new to Temporal** can pick up cold and complete on their own.

## Audience

- Comfortable Python scripters (functions, classes, dicts, requests/Netmiko-style
  scripts). Do not teach Python basics or a general async primer.
- New to Temporal: workflows, activities, workers, replay, determinism, durable timers,
  message passing, etc. These need real explanation with the "why".
- Know Arista EOS, `show` commands, config workflows, and a source of truth (Nautobot).
- Working alone, without the author present to explain.

## Goals

1. Every Temporal feature in the existing plan (`docs/feature-checklist.md`) is taught
   with a plain explanation, a network analogy, and working code.
2. **Nothing is used before it is explained or built.** Every function, constant and
   env var a snippet references either exists in the repo already or is written in that
   day's lesson.
3. **A complete, runnable, commented solution for every day.**
4. Everything runs **locally** on a laptop: Temporal dev server in a container,
   containerlab cEOS, a Nautobot instance, Python workers as local processes.
5. Every device/Nautobot activity has a **mock mode**, so Temporal-only learning works
   without the lab running, and so tests run in CI.

## Non-goals

- Production deployment: **no OpenShift, CRC, kind, or Kubernetes days.** The author's
  team runs the server in a container and workers on OCP at work, but the course stays
  local so teammates can practice on their own.
- Teaching Python, asyncio in general, EOS, or Nautobot administration.
- Temporal Cloud.

## Anti-goals (failure even if it "works")

- A lesson whose code references something undefined, or whose "Learn" text doesn't
  match what the lab has the learner do.
- Silent library switches. Each library is introduced on purpose, with a sentence on
  why it's the right tool for that day.
- Solutions that are fragments. A solution must run as-is.
- Terse bullet-point lessons. Lessons are prose-first, then code.

## Decisions made with the author

### Device libraries: pyeapi, Netmiko, NAPALM (all three, introduced on purpose)

| Library | Introduced | Why there |
| --- | --- | --- |
| **pyeapi** | Day 2 | Clean JSON from `show version`, so the learner focuses on activities, timeouts, retries |
| **Netmiko** | Day 5 | Slow, blocking SSH screen-scraping (e.g. `show tech` command by command), ideal for heartbeats and cancellation |
| **NAPALM** (`eos` driver) | Day 7 backup (`get_config`), Day 17 saga | `load_merge_candidate` → `compare_config` → `commit_config` → `rollback` maps onto Temporal's saga/compensation pattern |
| **pynautobot** | Day 7 | Intent side (builder's call, approved in conversation) |

All of these are **blocking**, so from Day 2 the course teaches the rule: blocking
libraries go in plain `def` activities run on a worker `activity_executor`
(`ThreadPoolExecutor`). Remove `niquests` from the curriculum and dependencies.
The author has used NAPALM most; Netmiko and pyeapi are new-ish to them.

### Local-only environment

- Temporal: `lab/start-temporal.sh` (dev server container, `--db-filename`
  persistence, `default` + `compliance` namespaces). Keep.
- cEOS: `lab/ceos-clab.clab.yml`, 4 nodes (`bos-rtr-01`, `bos-acc-01`, `nyc-rtr-01`,
  `nyc-acc-01`). Startup configs must enable eAPI **and SSH** with known credentials
  (`admin`/`admin`) so pyeapi, Netmiko and NAPALM all work.
- Nautobot: containerized in the lab (see "Nautobot" below), with a seed script.
- Former OCP content is replaced:
  - **Day 21**: production-shaped workers *locally* — split orchestration vs device-I/O
    workers on separate task queues as separate processes, rate limits, graceful
    shutdown, payload codec; optionally one worker in a local container.
  - **Day 30**: Worker Versioning locally — run v1 and v2 workers side by side, shift
    traffic, watch pinned vs auto-upgrade workflows; CI runs lint + tests + replay tests.

### Nautobot: containerized, latest release

- Target the **latest Nautobot container release** at build time (2.x+ data model:
  Locations/LocationTypes, not Sites). Pin the exact image tag that was verified.
- Add a containerized Nautobot to the lab: `lab/nautobot/` with a compose file
  (Nautobot + PostgreSQL + Redis), working with Podman or Docker, plus a start script
  and a seed script that creates the 4 devices, 2 locations (bos, nyc), roles, and the
  intent data used later. Documented in `docs/lab-setup.md`.

### AI week (Days 25–28): GitHub Copilot

- The team's LLM access is **GitHub Copilot**. Every AI lesson and solution uses it.
- *Builder's call, to verify at build time:* reach Copilot-family models through
  GitHub's OpenAI-compatible model inference endpoint (GitHub Models, authenticated
  with a GitHub token), so Temporal's OpenAI Agents SDK integration can still be used
  with a custom base URL. If the current GitHub offering (e.g. a Copilot SDK) makes a
  different route clearly better, use that and say why in the Day 25 lesson.
- A **mock LLM** (canned structured responses) exists so the AI days run and pass
  tests without a token, consistent with device mock mode.
- `.env.example` replaces `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` with the GitHub token
  variable(s) the chosen route needs.

### Delivery: pilot first

1. **Phase 1 (pilot):** shared pieces (constants/`DEVICE_HOSTS` parsing, mock layer,
   lab changes incl. containerized Nautobot + seed, cEOS SSH/eAPI config, CI running
   solution tests) **plus Days 1–7** with full lessons and solutions. Then **stop for
   the author's review** of depth, tone, and solution layout.
2. **Phase 2:** Days 8–30, applying the feedback from the pilot.

### Lesson format (every day)

`days/<week>/day-NN-<slug>/README.md` with sections:

1. **Why today matters**: the network problem, and the Temporal feature that solves it.
2. **Concept**: prose explanation with a network analogy (e.g. a workflow is a change
   ticket that remembers every step it took). Diagrams where they help.
3. **Walkthrough**: build the code step by step, explaining every new line. Every
   helper used is shown or linked to where it was built.
4. **Run it**: exact commands, expected output, what to look at in the UI/CLI.
5. **Break it**: deliberate failures and what the learner should observe.
6. **Check yourself**: questions with answers (collapsed `<details>`).
7. Link to that day's solution.

### Solutions

- `solutions/day-NN/` holds **the complete working code as of the end of that day**,
  commented, with tests. A stuck learner can diff against it, or start the next day
  from it.
- The learner's own workspace is `src/netops_temporal/` (which starts as the Day 1
  baseline).
- Each solution's tests pass in mock mode.

### Curriculum order

Keep the existing 30-day sequence and feature coverage (see
`docs/feature-checklist.md`), with these changes:

- Day 2: pyeapi + sync activities on a thread pool (timeouts, retry policy).
- Day 3: Pydantic models; map pyeapi auth failures to non-retryable `AuthError`.
- Day 5: Netmiko for heartbeats/cancellation (was a pyeapi snippet).
- Day 7: NAPALM `get_config` parallel backup + pynautobot intent.
- Day 17: saga implemented with NAPALM candidate/commit/rollback.
- Day 21 and Day 30: local versions as described above.
- The Codespaces/devcontainer path is secondary (mock mode makes it possible); keep it
  working only if cheap. *(Builder's call.)*

## Constraints

- Python 3.13, `temporalio` >= 1.34, `uv`, pytest with `WorkflowEnvironment`.
- Podman or Docker for Temporal; containerlab in a Linux VM (e.g. OrbStack) on macOS.
  Keep the macOS-reachability guidance from `docs/lab-setup.md`.
- One device-host map, parsed once in code (e.g. `DEVICE_HOSTS` env →
  `dict[str, str]` in `constants.py`), used by every activity.
- Device activities read credentials from env (`DEVICE_USERNAME`, `DEVICE_PASSWORD`).

## Left to the builder

- Exact solution packaging (copied packages per day, how a solution is run/imported,
  how CI runs all solution test suites).
- Where intent lives in Nautobot (config context vs custom fields).
- Mock fixture format.
- Wording, diagrams, and analogies per lesson; the exact list of "Break it" exercises.
- Whether to keep `.devcontainer/`.
- How live-lab behaviour is verified when no cEOS lab is available to the builder
  (mock-mode tests are mandatory; live mode should be checked where possible and
  marked as not lab-verified otherwise).
