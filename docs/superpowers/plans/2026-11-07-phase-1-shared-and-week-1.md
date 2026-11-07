# Phase 1 (Shared Pieces + Days 1–7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the repo's shared plumbing and Week 1 into a real course: a working local lab (Temporal, cEOS, containerized Nautobot), a mock mode, and Days 1–7 with full prose lessons and a complete runnable solution per day.

**Architecture:** The learner works in `src/netops_temporal/` (starts identical to the Day 1 solution). Each `solutions/day-NN/` holds a full copy of the `netops_temporal` package and its `tests/` as of the end of that day, run by putting that folder first on `PYTHONPATH`. All device and Nautobot access goes through small helper modules that switch to fixture-backed mocks when `LAB_MODE=mock`. A lesson checker enforces that every code snippet in a lesson appears verbatim in that day's solution.

**Tech Stack:** Python 3.13, `uv`, `temporalio>=1.34` (+ `temporalio.contrib.pydantic`), pydantic 2, pyeapi, Netmiko, NAPALM (`eos` driver), pynautobot, pytest + pytest-asyncio, ruff, Podman/Docker, containerlab, Nautobot container (latest release, pinned).

**Spec:** `docs/superpowers/specs/2026-11-07-temporal-30-days-rewrite-design.md`

## Global Constraints

- Python 3.13, `temporalio>=1.34`, managed with `uv`; tests use `temporalio.testing.WorkflowEnvironment` / `ActivityEnvironment`.
- Load the `temporal-developer` skill (in `.claude/skills/`) before writing Temporal code; verify SDK behaviour against it or docs.temporal.io rather than memory.
- Device libraries: **pyeapi** (Day 2), **Netmiko** (Day 5), **NAPALM `eos`** (Day 7); **pynautobot** for intent. Remove `niquests` everywhere.
- All four libraries are blocking → their activities are plain `def` activities; the worker sets `activity_executor=ThreadPoolExecutor(max_workers=10)`.
- Everything runs locally. No OpenShift/CRC/kind/Kubernetes content.
- Device credentials from env `DEVICE_USERNAME` / `DEVICE_PASSWORD` (lab default `admin`/`admin`). One host map, parsed once in `constants.py`.
- Nothing is used before it is explained or built: every name in a lesson snippet exists in that day's solution or an earlier day's.
- Lessons are prose-first. Section order, exactly: `## Why today matters`, `## Concept`, `## Walkthrough`, `## Run it`, `## Break it`, `## Check yourself` (answers in `<details>`), `## Solution` (link to `solutions/day-NN/`). Keep the existing prev/next nav line under the H1.
- Each solution's tests pass in mock mode with no lab running.
- Live behaviour that cannot be exercised by the implementer (no cEOS available) is marked in the task report as "not lab-verified"; never claimed as verified.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Locked decisions (implementer's calls already made)

- Mode flag is **`LAB_MODE`** (`live` | `mock`, default `live`), replacing `DEVICE_MODE`; it covers devices and Nautobot (and the LLM in Phase 2). Read per call via `lab_mode()`, never cached at import.
- Mock failure injection env vars: `MOCK_UNREACHABLE` (comma list of devices → raise `DeviceUnreachableError`), `MOCK_AUTH_FAIL` (`1` → raise `DeviceAuthError`), `MOCK_CLI_DELAY` (float seconds slept per CLI command).
- Fixtures ship inside the package: `netops_temporal/fixtures/` (`eapi/<device>.json` = command → JSON result, `cli/show_tech/<NN>.txt`, `configs/<device>.cfg`, `nautobot/intent.json`).
- Lab mgmt network: dedicated containerlab mgmt network `clab-mgmt`, `172.20.20.0/24`, static IPs `bos-rtr-01=172.20.20.2, bos-acc-01=172.20.20.3, nyc-rtr-01=172.20.20.4, nyc-acc-01=172.20.20.5`.
- Nautobot intent: native role + location, and a Device custom field `target_version` (key `target_version`). Mock intent: `4.32.0F` for all devices except `nyc-acc-01` = `4.33.1F` (deliberate drift for later weeks). Mock `show version`: model `cEOSLab`, version `4.32.0F`.
- Nautobot dev API token (preset via the image's superuser env vars): `0123456789abcdef0123456789abcdef01234567`; UI/API on `http://localhost:8080`, superuser `admin`/`admin`.
- Large output never goes into workflow history: activities write files under `OUTPUT_DIR` (env, default `output/`, gitignored) and return paths.

## Review Focus

1. **Malformed or missing `DEVICE_HOSTS` / unknown device name** → a clear error naming the bad pair or listing known devices, not a bare `KeyError`. Tests in Task 3.
2. **Worker on macOS can't reach cEOS mgmt IPs** → `check_lab` prints which check failed and points to the lab-setup networking section. Test in Task 3 (mock-driven).
3. **A solution run imports the learner's `src/` package instead of the solution's** (editable install shadowing) → `scripts/solution.sh` guarantees the solution wins. Test in Task 1.
4. **Lesson snippet drifts from the solution code** → `scripts/check_lessons.py` fails CI. Tests in Task 1.
5. **Re-running the Nautobot seed script** → idempotent, no duplicates or errors. Test in Task 2.

---

## File structure (end of Phase 1)

```
pyproject.toml                    # deps, pytest importlib mode
.env.example                      # LAB_MODE, DEVICE_*, NAUTOBOT_*, OUTPUT_DIR
scripts/solution.sh               # run any command against solutions/day-NN
scripts/test-solutions.sh         # run every (or selected) solution's tests
scripts/check_lessons.py          # snippet ⊂ solution + link checker
tests/test_check_lessons.py       # tests for the checker (root-level tooling tests)
tests/test_solution_runner.py
lab/ceos-clab.clab.yml            # static mgmt IPs
lab/startup-configs/*.conf        # admin/admin, eAPI https, SSH
lab/nautobot/compose.yml          # nautobot + postgres + redis
lab/nautobot/start.sh             # podman/docker compose up, wait for health
lab/nautobot/seed.py              # idempotent seed via pynautobot
lab/nautobot/test_seed.py
src/netops_temporal/              # learner workspace == solutions/day-01/netops_temporal
  constants.py                    # env, task queues, parse_device_hosts, device_host, lab_mode
  devices/errors.py               # DeviceUnreachableError, DeviceAuthError, UnknownDeviceError
  mock/devices.py  mock/nautobot.py
  fixtures/...
  tools/check_lab.py              # Day 1 lab connectivity check
  activities/ workflows/ workers/ starters/   # hello (Day 1)
tests/                            # == solutions/day-01/tests (+ tooling tests above)
solutions/day-01 … day-07/
  netops_temporal/  tests/
days/week-1/day-0N-*/README.md    # rewritten lessons
README.md, days/week-1/README.md, docs/lab-setup.md, lab/README.md, docs/codespaces.md
.github/workflows/ci.yml
```

Each later day's solution = previous day's solution + that day's additions. Files added per day:

| Day | Adds / changes |
| --- | --- |
| 02 | `devices/eapi.py`, `activities/facts.py`, `workflows/facts.py`, `starters/facts.py`, worker thread pool |
| 03 | `models.py`, `client.py`, error mapping in `devices/eapi.py`, typed facts |
| 04 | `FactsReport` with `collected_at` from `workflow.now()`; replay-detects-nondeterminism test |
| 05 | `devices/ssh.py`, `activities/show_tech.py`, `workflows/show_tech.py`, `starters/show_tech.py` |
| 06 | `tools/export_history.py`, `tests/histories/*.json`, replay + mocked-activity + retry tests |
| 07 | `devices/napalm_eos.py`, `sot/nautobot.py`, `activities/backup.py`, `workflows/backup.py`, `starters/backup.py` |

---

### Task 1: Repo tooling — dependencies, solution runner, lesson checker, CI

**Files:**
- Modify: `pyproject.toml`, `.github/workflows/ci.yml`, `.gitignore` (add `output/`)
- Create: `scripts/solution.sh`, `scripts/test-solutions.sh`, `scripts/check_lessons.py`
- Test: `tests/test_check_lessons.py`, `tests/test_solution_runner.py`

**Interfaces:**
- Produces:
  - `scripts/solution.sh NN <command...>` — runs `<command>` via `uv run` with `PYTHONPATH=solutions/day-NN` and `--env-file .env` only if `.env` exists. `NN` is two digits.
  - `scripts/test-solutions.sh [NN ...]` — for each given day (default: every `solutions/day-*`), runs `PYTHONPATH=solutions/day-NN uv run pytest -c pyproject.toml solutions/day-NN/tests -q`; exits non-zero if any fail; prints a per-day pass/fail summary.
  - `scripts/check_lessons.py [paths...]` (default: all `days/**/README.md`) with importable functions `extract_snippets(markdown: str) -> list[Snippet]`, `check_snippet(snippet: Snippet, solution_dir: Path) -> str | None` (error message or None), `check_links(md_path: Path) -> list[str]`, `main(argv) -> int`. `Snippet = (file: str, lines: list[str], line_no: int)`.
- Snippet rule: a fenced code block whose first line is `# file: <path>` is checked; `<path>` is relative to the lesson's solution dir (`solutions/day-NN/`, NN parsed from the lesson folder name `day-NN-*`). Every non-blank line after the header, except lines that are exactly `...` (after stripping), must appear in the target file **in order** (subsequence match on `rstrip()`-ed lines, preserving indentation). Blocks without the header are ignored.
- Link rule: every relative Markdown link target (strip `#anchor`) must exist on disk.

- [ ] **Step 1: Update `pyproject.toml`.** Dependencies: `temporalio>=1.34`, `pydantic>=2.9`, `pyeapi`, `netmiko`, `napalm`, `pynautobot` (latest compatible with 3.13; pin floors to the versions `uv lock` resolves). Remove `niquests`. Add `[tool.pytest.ini_options] addopts = "--import-mode=importlib"`. Run `uv sync` — expected: resolves and installs on Python 3.13. If any library fails on 3.13, stop and report.
- [ ] **Step 2: Write failing tests** in `tests/test_check_lessons.py`:
  - `test_snippet_matching_in_order_passes` — file has lines A,B,C; snippet `# file: x.py` + A, `...`, C → `None`.
  - `test_snippet_line_missing_fails` — snippet contains line D not in file → message contains `x.py` and `D`.
  - `test_snippet_out_of_order_fails` — C then A → error.
  - `test_block_without_header_ignored` — `extract_snippets` returns `[]`.
  - `test_broken_relative_link_reported` — md links `[x](missing.md)` → one error; `[y](https://e.com)` ignored; `[z](real.md#a)` ok.
  - `test_solution_dir_from_lesson_path` — `days/week-1/day-02-eapi-activity/README.md` → `solutions/day-02`.
- [ ] **Step 3:** `uv run pytest tests/test_check_lessons.py -v` → FAIL (module not found).
- [ ] **Step 4: Implement `scripts/check_lessons.py`** (import in tests via `importlib` from path).
- [ ] **Step 5:** Re-run → PASS.
- [ ] **Step 6: Write failing test** `tests/test_solution_runner.py::test_solution_package_shadows_src` — a fixture creates `solutions/day-99/netops_temporal/__init__.py` in the real repo (removed on teardown), runs `scripts/solution.sh 99 python -c "import netops_temporal; print(netops_temporal.__file__)"`, assert output contains `solutions/day-99`. Skip if `uv` not on PATH.
- [ ] **Step 7:** Run → FAIL; implement both shell scripts (`set -euo pipefail`, run from repo root regardless of cwd); run → PASS. If the editable install shadows `PYTHONPATH`, fix in the script (e.g. `uv run --no-project` with the venv's deps) and keep the test green.
- [ ] **Step 8: CI** (`.github/workflows/ci.yml`): `uv sync`; `uv run ruff check src tests solutions scripts lab`; `uv run pytest -q` (root); `scripts/test-solutions.sh`; `uv run python scripts/check_lessons.py`; `diff -r src/netops_temporal solutions/day-01/netops_temporal` and `diff -r tests solutions/day-01/tests -x test_check_lessons.py -x test_solution_runner.py -x __pycache__` (both must be empty). Steps that need folders created later may fail until Task 4 — acceptable within the phase; note it in the commit message.
- [ ] **Step 9: Commit** — `git commit -m "tooling: deps, solution runner, lesson checker, CI"`.

---

### Task 2: Lab — cEOS configs, containerized Nautobot, seed, setup docs

**Files:**
- Modify: `lab/ceos-clab.clab.yml`, `lab/startup-configs/{bos-rtr-01,bos-acc-01,nyc-rtr-01,nyc-acc-01}.conf`, `lab/README.md`, `docs/lab-setup.md`, `.env.example`
- Create: `lab/nautobot/compose.yml`, `lab/nautobot/start.sh`, `lab/nautobot/seed.py`
- Test: `lab/nautobot/test_seed.py`

**Interfaces:**
- Produces: `.env.example` keys — `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `LAB_MODE=live`, `DEVICE_USERNAME=admin`, `DEVICE_PASSWORD=admin`, `DEVICE_HOSTS=bos-rtr-01=172.20.20.2,bos-acc-01=172.20.20.3,nyc-rtr-01=172.20.20.4,nyc-acc-01=172.20.20.5`, `NAUTOBOT_URL=http://localhost:8080`, `NAUTOBOT_TOKEN=0123456789abcdef0123456789abcdef01234567`, `OUTPUT_DIR=output`, commented `MOCK_UNREACHABLE=`, `MOCK_AUTH_FAIL=`, `MOCK_CLI_DELAY=`. Drop `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` (Phase 2 adds the GitHub token).
- Produces: `seed.py` function `seed(api) -> dict[str, int]` (counts of created objects) taking a pynautobot `api` object; CLI `uv run python lab/nautobot/seed.py` reads `NAUTOBOT_URL`/`NAUTOBOT_TOKEN`.

- [ ] **Step 1: Topology.** `mgmt: {network: clab-mgmt, ipv4-subnet: 172.20.20.0/24}`; per-node `mgmt-ipv4` per Locked decisions. Keep links and image.
- [ ] **Step 2: Startup configs.** Replace the hashed admin line with `username admin privilege 15 role network-admin secret admin`; keep `management api http-commands` / `no shutdown` (HTTPS); ensure `management ssh` is not shut; drop `management http-server protocol http` (HTTPS only, so pyeapi/NAPALM use `https`). Keep routing config.
- [ ] **Step 3: Compose.** `lab/nautobot/compose.yml`: services `db` (postgres), `redis`, `nautobot` (image `networktocode/nautobot:<latest stable tag at build time, pinned>`), port `8080:8080`, env for DB/redis plus `NAUTOBOT_CREATE_SUPERUSER=true`, `NAUTOBOT_SUPERUSER_NAME=admin`, `NAUTOBOT_SUPERUSER_PASSWORD=admin`, `NAUTOBOT_SUPERUSER_API_TOKEN=<token>`, a healthcheck, named volumes. `start.sh`: uses `podman compose` or `docker compose` (`ENGINE` env like `lab/start-temporal.sh`), waits until `GET /health/` returns 200 (timeout 5 min, prints progress).
- [ ] **Step 4: Write failing tests** `lab/nautobot/test_seed.py` using an in-memory fake of the pynautobot endpoints `seed` uses (`get(**filters)` / `create(**fields)` per endpoint):
  - `test_seed_creates_four_devices_with_target_version` — after `seed(fake)`, devices `bos-rtr-01, bos-acc-01, nyc-rtr-01, nyc-acc-01` exist with locations `BOS`/`NYC`, roles `router`/`access`, custom field `target_version` matching the Locked decisions.
  - `test_seed_is_idempotent` — second `seed(fake)` returns all-zero counts and creates nothing.
- [ ] **Step 5:** Run `uv run pytest lab/nautobot/test_seed.py -v` → FAIL; implement `seed.py` (location type, locations, manufacturer Arista, device type `cEOSLab`, platform `eos`, roles with `dcim.device` content type, status Active lookup, custom field `target_version` on `dcim.device`, devices; get-or-create for each); run → PASS.
- [ ] **Step 6: Live check if possible.** If Podman/Docker is available: `lab/nautobot/start.sh`, then `uv run python lab/nautobot/seed.py` twice; expected second run reports nothing created; `curl -H "Authorization: Token <token>" localhost:8080/api/dcim/devices/?name=nyc-acc-01` shows `target_version: 4.33.1F`. Otherwise record "not lab-verified".
- [ ] **Step 7: Docs.** Rewrite `docs/lab-setup.md` as an ordered bring-up: prerequisites → Temporal (`lab/start-temporal.sh`) → cEOS (containerlab in Linux VM, static IPs) → Nautobot (`start.sh`, `seed.py`) → `.env` → `check_lab` (Task 3) → mock mode for when the lab is down. Keep the macOS reachability section (worker in VM / container on `clab-mgmt` / port forwards) and add the SSH (port 22) case for Netmiko. Update `lab/README.md` bring-up and tear-down to include Nautobot.
- [ ] **Step 8: Commit** — `git commit -m "lab: static mgmt IPs, eAPI+SSH creds, containerized Nautobot with seed"`.

---

### Task 3: Day 1 baseline code — constants, errors, mocks, fixtures, check_lab

**Files:**
- Modify: `src/netops_temporal/constants.py`
- Create: `src/netops_temporal/devices/__init__.py`, `devices/errors.py`, `mock/__init__.py`, `mock/devices.py`, `mock/nautobot.py`, `fixtures/eapi/<4 devices>.json`, `fixtures/cli/show_tech/01.txt … 10.txt`, `fixtures/configs/<4 devices>.cfg` (from `lab/startup-configs`), `fixtures/nautobot/intent.json`, `tools/__init__.py`, `tools/check_lab.py`
- Test: `tests/test_constants.py`, `tests/test_mock.py`, `tests/test_check_lab.py`

**Interfaces:**
- Produces (`constants.py`): `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `ORCHESTRATION_TASK_QUEUE = "netops-orchestration"`, `DEVICE_IO_TASK_QUEUE = "netops-device-io"`, `DEVICE_USERNAME`, `DEVICE_PASSWORD`, `NAUTOBOT_URL`, `NAUTOBOT_TOKEN`, `OUTPUT_DIR: Path`, `DEFAULT_DEVICE_HOSTS: str` (the four-device string), `parse_device_hosts(raw: str) -> dict[str, str]`, `DEVICE_HOSTS: dict[str, str]`, `DEVICES: list[str]` (keys in order), `device_host(device: str) -> str`, `lab_mode() -> Literal["live", "mock"]`, `SHOW_TECH_COMMANDS: list[str]` (the 10 commands below; single source of truth, used by `mock/devices.py` now and `activities/show_tech.py` on Day 5). Remove `DEVICE_MODE` and `ORCHESTRATOR_WORKFLOW_ID`.
- Produces (`devices/errors.py`): `DeviceUnreachableError(Exception)`, `DeviceAuthError(Exception)`, `UnknownDeviceError(ValueError)`.
- Produces (`mock/devices.py`): `show(device: str, commands: list[str]) -> list[dict]`, `cli(device: str, command: str) -> str`, `running_config(device: str) -> str`; `constants.SHOW_TECH_COMMANDS` is (10 commands, e.g. `show version`, `show interfaces status`, `show ip interface brief`, `show ip route`, `show ip ospf neighbor`, `show lldp neighbors`, `show logging last 50`, `show processes top once`, `show running-config`, `show inventory`; `cli()` maps command index → `fixtures/cli/show_tech/NN.txt`). All three call `device_host(device)` first (unknown → `UnknownDeviceError`) and honour `MOCK_UNREACHABLE`, `MOCK_AUTH_FAIL`; `cli` sleeps `MOCK_CLI_DELAY`.
- Produces (`mock/nautobot.py`): `device_intent(device: str) -> dict` with keys `device, role, location, target_version`.
- Produces (`tools/check_lab.py`): `run_checks() -> list[CheckResult]` with `CheckResult(name: str, ok: bool, detail: str)`; checks Temporal (connect to `TEMPORAL_ADDRESS`), per-device eAPI (`show version` via pyeapi) and SSH (TCP 22 connect), Nautobot (`/api/status/` with token). In mock mode device/Nautobot checks report `ok=True, detail="mock mode"`. CLI `python -m netops_temporal.tools.check_lab` prints a table and, for any failed device check, the hint `See docs/lab-setup.md#macos-networking`; exit code 1 on any failure.

- [ ] **Step 1: Failing tests** `tests/test_constants.py`:
  - `test_parse_device_hosts_basic` — `"a=1.1.1.1, b=2.2.2.2"` → `{"a": "1.1.1.1", "b": "2.2.2.2"}`.
  - `test_parse_device_hosts_ignores_empty_segments` — `"a=1.1.1.1,,"` → `{"a": "1.1.1.1"}`.
  - `test_parse_device_hosts_rejects_malformed` — `"a1.1.1.1"` → `ValueError` whose message contains `a1.1.1.1` and `DEVICE_HOSTS`.
  - `test_device_host_unknown_lists_known` — `device_host("nope")` → `UnknownDeviceError` with message containing `bos-rtr-01`.
  - `test_lab_mode_reads_env_each_call` — monkeypatch `LAB_MODE=mock` → `"mock"`; unset → `"live"`; `LAB_MODE=bogus` → `ValueError`.
- [ ] **Step 2: Failing tests** `tests/test_mock.py`:
  - `test_show_version_fixture` — `show("bos-rtr-01", ["show version"])[0]` has `modelName == "cEOSLab"`, `version == "4.32.0F"`.
  - `test_unreachable_injection` — `MOCK_UNREACHABLE=bos-rtr-01` → `DeviceUnreachableError`; other devices fine.
  - `test_auth_fail_injection` — `MOCK_AUTH_FAIL=1` → `DeviceAuthError`.
  - `test_running_config_is_lab_startup_config` — contains `hostname nyc-acc-01`.
  - `test_intent_drift_fixture` — `device_intent("nyc-acc-01")["target_version"] == "4.33.1F"`, others `4.32.0F`.
  - `test_cli_returns_ten_distinct_outputs` — every command in `SHOW_TECH_COMMANDS` returns non-empty text.
- [ ] **Step 3: Failing test** `tests/test_check_lab.py::test_failed_device_check_prints_hint` — monkeypatch `run_checks` to return one failing device check; run `main()`; captured stdout contains `docs/lab-setup.md#macos-networking`; return code 1. And `test_mock_mode_skips_devices` — `LAB_MODE=mock` and a stubbed Temporal check → all device results `detail == "mock mode"`.
- [ ] **Step 4:** `uv run pytest tests -v` → new tests FAIL.
- [ ] **Step 5:** Implement. Make sure the anchor `#macos-networking` exists in `docs/lab-setup.md` (heading text "macOS networking"). Run → PASS; `uv run ruff check src tests` clean.
- [ ] **Step 6: Commit** — `git commit -m "baseline: constants, mock lab layer, fixtures, check_lab"`.

---

### Task 4: Day 1 lesson, `solutions/day-01`, top-level docs

**Files:**
- Create: `solutions/day-01/netops_temporal/` (copy of `src/netops_temporal/`), `solutions/day-01/tests/` (copy of `tests/` minus the two tooling tests)
- Modify: `days/week-1/day-01-lab-up/README.md`, `days/week-1/README.md`, `README.md`, `src/netops_temporal/workers/main.py` and starters (docstring/comments only if needed)

**Interfaces:**
- Consumes: Task 1 scripts, Task 3 baseline.
- Produces: the lesson format all later lessons copy; README sections "How this course works" and "Using the solutions" that later lessons link to.

- [ ] **Step 1: Copy** the baseline into `solutions/day-01/`. Run `scripts/test-solutions.sh 01` → PASS, and the two `diff -r` commands from Task 1 Step 8 → empty.
- [ ] **Step 2: Write the Day 1 lesson.** Content the lesson must cover:
  - *Why today matters:* scripts die mid-change and forget where they were; Temporal remembers.
  - *Concept:* workflow / activity / worker / task queue / event history, with the analogy "workflow = change ticket that records every step; activity = a step that touches the network; worker = the engineer who picks tickets off a queue; task queue = the queue." A diagram (ASCII or Mermaid) of client → server → task queue → worker. Explain that the worker holds no durable state.
  - *Walkthrough:* tour of `src/netops_temporal/` file by file: `constants.py` (including `DEVICE_HOSTS` parsing and `lab_mode()`), the provided `mock/` + `fixtures/` (why they exist), `tools/check_lab.py`, then `HelloWorkflow` / `say_hello` / worker / starter line by line with `# file:` snippets.
  - *Run it:* `cp .env.example .env`, `uv sync`, `lab/start-temporal.sh`, `uv run --env-file .env python -m netops_temporal.tools.check_lab`, worker, starter, then the CLI commands (`temporal workflow list/describe/show`, `-o json`), plus the "no CLI on your Mac" podman exec variant.
  - *Break it:* stop worker → start workflow → pending; restart → completes; restart Temporal container → history persists.
  - *Check yourself:* name each event in HelloWorkflow's history and who produced it; why can you kill a worker safely; what is a task queue for. Answers in `<details>`.
  - *Solution:* link to `solutions/day-01/`, and a short "how to use solutions" pointer to the README section.
- [ ] **Step 3: README.md** rewrite: who it's for (Python-fluent network automation engineers new to Temporal), what you'll build, local lab summary (Temporal + 4 cEOS + Nautobot), mock mode, how a day is structured, "Using the solutions" (diff with `diff -r src/netops_temporal solutions/day-NN/netops_temporal`; run with `scripts/solution.sh NN ...`; restart from a day with `rm -rf src/netops_temporal && cp -r solutions/day-NN/netops_temporal src/`), the 30-day table (Day 21 → "Production-shaped workers, locally"; Day 30 → "Worker Versioning locally + CI"; ☁️ column replaced by a "Needs lab?" column: Days 1, 4, 6 = no; 2, 3, 5, 7 = optional (mock works)), a note that Days 8–30 are outlines being rewritten, and repo layout including `solutions/` and `scripts/`. Remove the OCP architecture box text; keep the architecture diagram minus OCP. Update `days/week-1/README.md` day titles to match.
- [ ] **Step 4: Verify:** `uv run python scripts/check_lessons.py` → exit 0 for Day 1 (other lessons have no `# file:` blocks yet, and their links must still resolve — fix any broken ones you touched).
- [ ] **Step 5: Commit** — `git commit -m "day 01: full lesson, solution snapshot, course README"`.

---

### Tasks 5–10: one task per day (Days 2–7)

Every day task follows the same steps; only the content table differs.

**Common steps for Day N:**

- [ ] **Step 1:** `cp -r solutions/day-(N-1) solutions/day-N` (exclude `__pycache__`).
- [ ] **Step 2: Write the failing tests** listed for the day into `solutions/day-N/tests/`.
- [ ] **Step 3:** `scripts/test-solutions.sh N` → new tests FAIL.
- [ ] **Step 4: Implement** the day's interfaces in `solutions/day-N/netops_temporal/`. Register new workflows/activities in `workers/main.py`. Comments explain *why* (Temporal reasoning), not what.
- [ ] **Step 5:** `scripts/test-solutions.sh N` → PASS; `uv run ruff check solutions/day-N` clean.
- [ ] **Step 6: Live run if a lab is reachable** (`check_lab` green): run the day's "Run it" commands via `scripts/solution.sh N ...` and confirm the expected output; otherwise run them with `LAB_MODE=mock` against the local Temporal dev server if available, and mark live behaviour "not lab-verified".
- [ ] **Step 7: Write the lesson** `days/week-1/day-0N-*/README.md` in the Global Constraints format, covering the day's Concept points and Break-it items below. Every code block that shows solution code starts with `# file: <path>`; walk through every new line that introduces a Temporal API or a library call. The Run-it section gives both live and `LAB_MODE=mock` commands and the expected output.
- [ ] **Step 8:** `uv run python scripts/check_lessons.py days/week-1/day-0N-*/README.md` → exit 0.
- [ ] **Step 9: Commit** — `git commit -m "day 0N: <topic> lesson and solution"`.

---

### Task 5: Day 02 — first real activity with pyeapi (sync activities, timeouts, retries)

**Interfaces:**
- Consumes: `device_host`, `DEVICE_USERNAME/PASSWORD`, `lab_mode`, `mock.devices.show`, `DEVICES`, `ORCHESTRATION_TASK_QUEUE`.
- Produces:
  - `devices/eapi.py`: `run_show(device: str, commands: list[str]) -> list[dict]` — mock → `mock.devices.show`; live → `pyeapi.connect(transport="https", host=device_host(device), username=..., password=..., return_node=True).run_commands(commands)`.
  - `activities/facts.py`: `@activity.defn def get_device_facts(device: str) -> dict` returning `{"device", "model", "version"}` (sync `def`).
  - `workflows/facts.py`: `GetFactsWorkflow.run(device: str) -> dict`, calling the activity with `start_to_close_timeout=30s`, `RetryPolicy(initial_interval=2s, backoff_coefficient=2.0, maximum_attempts=5)`.
  - `workers/main.py`: `activity_executor=ThreadPoolExecutor(max_workers=10)`.
  - `starters/facts.py`: `python -m netops_temporal.starters.facts [device ...]` (default `DEVICES`), workflow id `facts-<device>`, runs all concurrently with `asyncio.gather`, prints one line per device.

**Tests (`tests/test_facts.py`, `LAB_MODE=mock` via monkeypatch):**
- `test_get_device_facts_mock` — via `ActivityEnvironment().run(get_device_facts, "bos-rtr-01")` → `{"device": "bos-rtr-01", "model": "cEOSLab", "version": "4.32.0F"}`.
- `test_facts_workflow_end_to_end` — time-skipping env + worker with thread-pool executor → same dict.
- `test_facts_workflow_fails_after_five_attempts` — `MOCK_UNREACHABLE=bos-rtr-01` → `WorkflowFailureError` whose cause is `ActivityError`; history (`handle.fetch_history()`) shows attempt 5 on the `ActivityTaskStarted` event.

**Lesson content:**
- *Why:* a `show version` against a node that's rebooting; a script fails, a workflow waits and retries.
- *Concept:* activities are where I/O lives and are retried, workflows are not; the four timeouts (start-to-close, schedule-to-close, schedule-to-start, heartbeat→Day 5) with when to use each; default retry policy is unlimited — choose your own; **async vs sync activities**: pyeapi blocks, so `def` + thread pool, and what goes wrong if you call a blocking lib inside `async def` (worker event loop stalls, all workflows freeze).
- *Explicitly address the old confusion:* `run_commands` is **pyeapi's** `Node.run_commands`; our wrapper is named `run_show` to avoid ambiguity; `DEVICE_HOSTS` is parsed in `constants.py` (link Day 1).
- *Break it:* stop `bos-rtr-01` (or `MOCK_UNREACHABLE=bos-rtr-01` and restart the worker) and watch Pending Activities (attempt, last failure, next retry); restore before attempt 5 → completes; let it hit 5 → read the failure chain (WorkflowExecutionFailed ← ActivityError ← cause).
- *Check yourself:* activity failure vs workflow failure; why sync activity + thread pool; which timeout bounds one attempt.

---

### Task 6: Day 03 — Pydantic models and failures

**Interfaces:**
- Produces:
  - `models.py`: `FactsRequest(device: str)`, `DeviceFacts(device: str, model: str, version: str)`.
  - `client.py`: `async def connect() -> Client` — `Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, data_converter=pydantic_data_converter)`. Worker and all starters use it.
  - `devices/eapi.py`: live errors mapped — pyeapi connection failures/timeouts → `DeviceUnreachableError`; HTTP 401/403 (inspect how pyeapi surfaces it; verify against pyeapi source) → `DeviceAuthError`.
  - `activities/facts.py`: `get_device_facts(req: FactsRequest) -> DeviceFacts`; converts `DeviceAuthError` → `ApplicationError("auth failed for <device>", type="AuthError", non_retryable=True)` and `UnknownDeviceError` → `ApplicationError(..., type="UnknownDevice", non_retryable=True)`; lets `DeviceUnreachableError` propagate (retryable).
  - `GetFactsWorkflow.run(req: FactsRequest) -> DeviceFacts`.

**Tests (`tests/test_facts.py`, updated):**
- `test_auth_failure_is_not_retried` — `MOCK_AUTH_FAIL=1` → workflow fails; cause `ApplicationError` with `type == "AuthError"`; history shows exactly one `ActivityTaskStarted` with attempt 1.
- `test_unknown_device_is_not_retried` — `FactsRequest(device="nope")` → `type == "UnknownDevice"`, one attempt.
- `test_unreachable_still_retries` — `MOCK_UNREACHABLE` → 5 attempts.
- `test_facts_roundtrip_typed` — result is a `DeviceFacts` instance.
- `test_eapi_maps_unauthorized` — patch pyeapi node to raise the pyeapi 401 error shape → `DeviceAuthError` (live path, no network).

**Lesson content:**
- *Concept:* why single input objects (add fields later without breaking running workflows); data converters and what's in a payload (show it in the UI); retryable vs non-retryable, `ApplicationError(type=..., non_retryable=True)` vs `RetryPolicy(non_retryable_error_types=[...])`; translating library exceptions at the device-layer boundary.
- *Break it:* wrong password in `.env` (or `MOCK_AUTH_FAIL=1`) → one attempt, `AuthError`; stopped node → still retries; add an optional field (`serial: str | None = None`) to `DeviceFacts` while a workflow is retrying → nothing breaks.
- *Check yourself:* classify each error you've seen as retryable or not and why; what would happen if auth errors retried forever.

---

### Task 7: Day 04 — determinism, the sandbox, replay

**Interfaces:**
- Produces: `models.FactsReport(facts: DeviceFacts, collected_at: datetime)`; `GetFactsWorkflow.run(req: FactsRequest) -> FactsReport` stamping `collected_at=workflow.now()`; workflow logs via `workflow.logger`.

**Tests (`tests/test_determinism.py`):**
- `test_collected_at_uses_workflow_time` — time-skipping env; `collected_at` equals the env's current time within 1 s (proves `workflow.now()`, not wall clock).
- `test_replay_detects_nondeterminism` — run `GetFactsWorkflow` to completion, `fetch_history()`, then `Replayer(workflows=[ChangedGetFactsWorkflow])` where the test-local class (same workflow name via `@workflow.defn(name="GetFactsWorkflow")`) calls a different activity first → replay raises a nondeterminism error. Also replay against the real class → succeeds.

**Lesson content:**
- *Concept:* how replay works (worker rebuilds state by re-running code against history; commands must match events), with a step-by-step event/command table for GetFactsWorkflow; what breaks determinism (`datetime.now()`, `random`, I/O, iterating sets, changing activity order) and the safe replacements (`workflow.now()`, `workflow.random()`, activities); the sandbox and `imports_passed_through` (why the existing workflows import activities that way); `workflow.logger` not printing duplicate lines on replay.
- *Break it:* temporarily put `datetime.now()` in the workflow — see the sandbox complain; add an extra activity call to a workflow while one is mid-retry and restart the worker → nondeterminism error in the UI; revert.
- *Check yourself:* why can activities call `datetime.now()` but workflows can't; what replay is for.

---

### Task 8: Day 05 — Netmiko, blocking libraries, heartbeats, cancellation

**Interfaces:**
- Produces:
  - `devices/ssh.py`: `@contextmanager def cli_session(device: str) -> Iterator[Callable[[str], str]]` — live: Netmiko `ConnectHandler(device_type="arista_eos", host=device_host(device), username, password)`, yields `conn.send_command`, disconnects on exit, maps Netmiko auth/timeout exceptions to `DeviceAuthError`/`DeviceUnreachableError`; mock: yields `lambda cmd: mock.devices.cli(device, cmd)`.
  - `models.ShowTechRequest(device: str)`, `models.ShowTechResult(device: str, output_dir: str, commands_collected: int, resumed_from: int)`.
  - `activities/show_tech.py`: iterates `constants.SHOW_TECH_COMMANDS`; `@activity.defn def collect_show_tech(req: ShowTechRequest) -> ShowTechResult` (sync): start index from `activity.info().heartbeat_details` (default 0); for each remaining command, write output to `OUTPUT_DIR/show-tech/<device>/<NN>.txt`, then `activity.heartbeat(i + 1)`; check `activity.is_cancelled()` after each heartbeat and stop cleanly (verify the correct sync-activity cancellation pattern for temporalio ≥1.34 via the skill/docs and use it).
  - `workflows/show_tech.py`: `ShowTechWorkflow.run(req: ShowTechRequest) -> ShowTechResult` with `start_to_close_timeout=10min`, `heartbeat_timeout=15s`, `RetryPolicy(maximum_attempts=3)`.
  - `starters/show_tech.py <device>`.

**Tests (`tests/test_show_tech.py`):**
- `test_collects_all_ten_and_heartbeats` — `ActivityEnvironment` with `on_heartbeat` recorder → `commands_collected == 10`, heartbeats `[1..10]`, ten files in a `tmp_path` `OUTPUT_DIR`.
- `test_resumes_from_heartbeat_details` — env info `heartbeat_details=[4]` → `resumed_from == 4`, only commands 5–10 executed (count `cli` calls).
- `test_result_contains_no_command_output` — serialized `ShowTechResult` JSON is < 1 KB (Review Focus: history stays small).
- `test_cancellation_stops_early` — cancel the `ActivityEnvironment` after the 3rd heartbeat → activity stops; fewer than 10 files.

**Lesson content:**
- *Concept:* why Netmiko (SSH screen scraping, slow, blocking); the event-loop rule again with a concrete failure; thread-pool sizing; heartbeats as liveness + progress checkpoint; `heartbeat_timeout` vs `start_to_close`; resuming from `heartbeat_details`; cancellation is delivered through heartbeats; keep big output out of history (write files, return paths).
- *Break it:* `MOCK_CLI_DELAY=3` (or live), kill the worker mid-collection, restart → resumes at the last heartbeat; cancel the workflow from the UI → activity stops and the workflow shows cancellation; set `heartbeat_timeout` shorter than one command and watch the timeout fire.
- *Check yourself:* async vs sync for each activity so far; what happens to heartbeats if the worker dies; why return a path instead of the output.

---

### Task 9: Day 06 — testing

**Interfaces:**
- Produces: `tools/export_history.py` — `python -m netops_temporal.tools.export_history <workflow_id> <out.json>` using `client.get_workflow_handle(id).fetch_history()` → `history.to_json()`; `tests/histories/get_facts.json` and `tests/histories/show_tech.json` (captured from runs; generating them inside the time-skipping env via `fetch_history()` is acceptable, document how they were made); `tests/conftest.py` with a `mock_lab` fixture (sets `LAB_MODE=mock`, `OUTPUT_DIR=tmp_path`) and a `workflow_env` fixture.

**Tests (consolidated and added):**
- `test_facts_workflow_with_stubbed_activity` — register a test-local `@activity.defn(name="get_device_facts")` returning fixed `DeviceFacts`; workflow returns it (no mock lab needed).
- `test_retry_backoff_uses_time_skipping` — with `MOCK_UNREACHABLE`, 5 attempts with backoff complete in < 5 s wall time.
- `test_replay_committed_histories` — `Replayer(workflows=[GetFactsWorkflow, ShowTechWorkflow])` replays every file in `tests/histories/` without error.
- Earlier tests refactored to use the fixtures; all still pass.

**Lesson content:**
- *Concept:* three test layers — activity unit tests (`ActivityEnvironment`), workflow tests (time-skipping `WorkflowEnvironment`, stubbed activities by name), replay tests (history files = safety net for every future code change, Day 19); when to use mock lab vs stubbed activities; exporting histories with the tool and with `temporal workflow show -o json`.
- *Break it:* change the order of calls in `ShowTechWorkflow`, run `pytest` → replay test fails; revert.
- *Check yourself:* which layer catches a nondeterministic change; why time-skipping matters for retry tests.

---

### Task 10: Day 07 — mini-project: parallel config backup (NAPALM) + intent (Nautobot)

**Interfaces:**
- Produces:
  - `devices/napalm_eos.py`: `get_running_config(device: str) -> str` — mock → `mock.devices.running_config`; live → `napalm.get_network_driver("eos")(host, username, password, optional_args={"transport": "https"})`, `open()`, `get_config(retrieve="running")["running"]`, `close()` in `finally`; error mapping as Day 3.
  - `sot/__init__.py`, `sot/nautobot.py`: `get_device_intent(device: str) -> DeviceIntent` — mock → `mock.nautobot.device_intent`; live → `pynautobot.api(NAUTOBOT_URL, token=NAUTOBOT_TOKEN).dcim.devices.get(name=device)` → role name, location name, `custom_fields["target_version"]`; device not found → `UnknownDeviceError`.
  - `models.py`: `DeviceIntent(device, role, location, target_version)`, `BackupRequest(devices: list[str] = Field(default_factory=lambda: list(DEVICES)))`, `BackupConfigRequest(device: str, timestamp: str)`, `IntentRequest(device: str)`, `DeviceBackupResult(device: str, ok: bool, backup_path: str | None = None, intent: DeviceIntent | None = None, error: str | None = None)`, `BackupReport(started_at: datetime, results: list[DeviceBackupResult])` with properties `succeeded: list[str]`, `failed: list[str]`.
  - `activities/backup.py`: `backup_running_config(req: BackupConfigRequest) -> str` (writes `OUTPUT_DIR/backups/<device>/<timestamp>.cfg`, returns path); `fetch_device_intent(req: IntentRequest) -> DeviceIntent`; same non-retryable mapping as Day 3.
  - `workflows/backup.py`: `ConfigBackupWorkflow.run(req: BackupRequest) -> BackupReport` — `timestamp` from `workflow.now()` (format `%Y%m%dT%H%M%SZ`); per device, one coroutine runs backup and intent concurrently and catches `ActivityError` into `ok=False, error=<cause message>`; all devices via `asyncio.gather`; activity options `start_to_close_timeout=60s`, `RetryPolicy(maximum_attempts=3)`.
  - `starters/backup.py [device ...]` prints a table: device, ok, backup path, target version, error.

**Tests (`tests/test_backup.py`):**
- `test_backup_all_devices_mock` — four results, all ok, four files exist, `nyc-acc-01` intent `target_version == "4.33.1F"`.
- `test_partial_failure_reported_not_raised` — `MOCK_UNREACHABLE=nyc-rtr-01` → workflow **completes**; `failed == ["nyc-rtr-01"]`, three succeeded, error text mentions unreachable.
- `test_backups_run_in_parallel` — history shows all four `backup_running_config` `ActivityTaskScheduled` events before any `ActivityTaskCompleted` (same workflow task).
- `test_timestamp_is_deterministic` — backup file name derives from `workflow.now()` (env time).
- `test_nautobot_device_not_found` — patch pynautobot `get` → `None` → `UnknownDeviceError`.
- Add `tests/histories/config_backup.json` and include it in the replay test.

**Lesson content:**
- *Concept:* fan-out with `asyncio.gather` inside a workflow (it is deterministic; activities run in parallel on the worker's thread pool); partial failure as data vs failing the whole workflow (and when each is right); NAPALM's normalized getters and why NAPALM for backups (sets up the Day 17 saga); Nautobot as intent via pynautobot; reusing Day 4 (`workflow.now()` for timestamps) and Day 3 (error typing).
- *Run it:* requires Nautobot seeded (or mock); show the starter table and the UI timeline view with parallel activities.
- *Break it:* stop one node mid-run → report shows 3/4; stop Nautobot → intent fails with retries then marks devices failed; raise `max_workers` to 2 and watch activities queue.
- *Check yourself / end-of-week checkpoint:* explain every event in the ConfigBackupWorkflow history.

---

### Task 11: Phase 1 wrap-up — docs consistency and full verification

**Files:**
- Modify: `docs/feature-checklist.md` (Days 1–7 lines reflect pyeapi/Netmiko/NAPALM; Day 21/30 lines say "locally"; remove OCP mentions), `docs/codespaces.md` (Codespaces = mock mode only, `LAB_MODE=mock`), `.devcontainer/post-create.sh` (remove anything niquests-specific; set `LAB_MODE=mock`), `LEARNING.md` (keep), `days/capstone/day-30-ocp-cicd/` → rename folder to `day-30-worker-versioning/` and update every link to it.

- [ ] **Step 1:** Make the edits above; `grep -rniE "niquests|DEVICE_MODE|openshift|\bOCP\b|CRC" --exclude-dir=.git --exclude-dir=.venv --exclude-dir=.claude .` → only hits are in Phase 2 outline lessons (Days 8–30, untouched content) and the spec/plan.
- [ ] **Step 2: Full verification:** `uv run ruff check src tests solutions scripts lab`; `uv run pytest -q`; `uv run pytest lab/nautobot -q`; `scripts/test-solutions.sh`; `uv run python scripts/check_lessons.py`; both `diff -r` checks. All must pass; paste the output summary in the task report.
- [ ] **Step 3:** Write a short `docs/phase-1-review.md` for the author: what changed, what's lab-verified vs mock-only, and the specific things to judge in review (lesson depth/tone, solution layout, mock mode, lab bring-up).
- [ ] **Step 4: Commit** — `git commit -m "phase 1: docs consistency and review notes"`.
