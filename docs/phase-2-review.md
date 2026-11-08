# Phase 2 review notes

Phase 2 wrote Days 8–30 in the Phase 1 format, so all 30 days are now full lessons. Please judge
the things listed under **What to judge** before this merges.

## What changed

| Area | Before | Now |
| --- | --- | --- |
| Lessons, Days 8–30 | Outlines | Full lessons, plus overviews for Weeks 2, 3 and 4 |
| Solutions | Days 1–7 | `solutions/day-01` … `day-30`, each complete and runnable: 22 tests on Day 1, 203 on Day 30 |
| Replay tests | Exports from Week 1 | Also cover the watch, remediation, audit and orchestrator workflows, including a two-cycle orchestrator run with approvals |
| AI week | GitHub Models through Copilot | Any OpenAI-compatible API, with Ollama as the default, because GitHub Models was retired on 2026-07-30 |
| OpenShift | Days 21 and 30 targeted it | Local versions: split workers and a container on Day 21, v1 and v2 side by side on Day 30 |
| Lab | One namespace | Adds the `compliance` namespace, search attributes, `lab/nexus-endpoint.sh` and `lab/deploy.sh` |
| Mock mode | Devices and Nautobot | Adds pushes that persist, `MOCK_VERIFY_FAIL`, a scripted model and `MOCK_LLM_MALFORMED` |

## Verified live

| Against | Days | What ran |
| --- | --- | --- |
| Your cEOS lab and Nautobot | 8, 14, 15, 17, 29 | Includes Day 14's first drift cycle, a real push and rollback on `bos-acc-01` (Day 17), and the full system on Day 29 with workers killed mid-cycle. The lab was rolled back afterwards |
| Ollama, `qwen2.5:7b` | 25–29 | Real explanations and agent runs, killing a worker mid-agent, a stopped model server, and a bad model name |
| Real dev server | 9–13, 16, 18–24, 30 | Schedules and backfills, a real non-determinism failure and its patch, a worker in a Podman container (Day 21), Nexus failures and cancellation, and a v1-to-v2 rollout |

`.superpowers/sdd/2026-11-07-phase-2-days-8-30/progress.md` has the observed result for each day. Its
entries for the third row don't always say whether the devices were real or mock, so assume mock
unless the entry says otherwise.

Final run on this branch: ruff clean, root tests 33 passed, lab tests 2 passed,
`scripts/test-solutions.sh` passed on all 30 days, `check_lessons.py` OK on 34 lessons, and `src/`
identical to Day 1.

Live runs found real bugs that the tests had missed. All of these are fixed:

- Cancelling the orchestrator could drop its Nexus cancel requests, so remediations pushed anyway
  (Day 23).
- Child workflows' search attributes were built in a form the SDK rejects (Days 20–22).
- A burst of entity backups collided on second-resolution file names (Day 13).
- An HTTP exception chain made an LLM failure too large to store (Day 25).
- The Agents SDK uploads traces, including device output, to OpenAI by default. It's now off (Day 26).
- `lab/deploy.sh` could leave the two namespaces on different builds (Day 30).

## Not verified live

- **GitHub Actions**, including the new cache of the Temporal server downloads. The steps pass
  locally, but the cache paths assume the runner's temp directory is `/tmp`.
- **Codespaces.** `.devcontainer/start-temporal.sh` now registers the search attributes, with the
  same flags as `lab/start-temporal.sh`, but it hasn't run in a Codespace.
- **Day 30 in `temporal-dev`, or as containers.** It ran on a CLI dev server with worker processes,
  not on the `lab/start-temporal.sh` container. Setting `BUILD_ID` on a worker image and the Temporal
  Worker Controller weren't tried, and the lesson says so.
- **Hosted model providers.** Only Ollama was run. The hosted settings on Day 25 are untested.
- **Docker** for the lab scripts (Podman only), as in Phase 1.
- **The new cEOS topology from Phase 1**, unless you've since redeployed it.
- **The learner's path through `src/`.** Live checks ran the solutions, not someone typing each day
  into `src/`.

## Known limits, on purpose

- The saga verifies by looking for each pushed line in the running config, so an approved negation
  like `no shutdown` always rolls back on a real device. Day 27 explains this.
- The approval gate is opt-in (`--approve medium,high`). An operator who forgets it gets no gate.
- If the model is down and the gate is on, every fix waits for a person.
- An approval stands in for a change ticket (`approved by bob`) when `REQUIRE_TICKET=1`.
- `DeviceUpgradeWorkflow` is a stand-in, because cEOS can't be upgraded in place.
- The replay test doesn't know about pinning, so changing a pinned workflow can fail it even when
  running workflows are safe. Day 30 explains how to decide.

## Still open

`DeviceEntityWorkflow` and `TroubleshootWorkflow` auto-upgrade but have no recorded history, so the
replay test can't catch a breaking change to them. Day 30 says so. Recording a troubleshoot history
is more work than the others, because the agent plugin brings its own payload converter.

## What to judge

1. **The AI week's provider.** Is Ollama the right default for your team's laptops? `qwen2.5:7b` is
   about 4.7 GB, and agent runs took 46 s in testing.
2. **Time per day.** The README says 60–90 minutes, but Days 29 and 30 are marked as 2 hours. Change
   the promise, or trim those days?
3. **`behavior()`.** Workflows read `BUILD_ID` to decide what to declare, so Days 1–29 keep running
   unversioned. It works and is tested, but it's the least obvious code in the course.
4. **Week 4 and the capstone.** Read Days 23, 26 and 29 end to end. Is that much concept too much for
   teammates who are new to Temporal?
5. **Production mapping.** Does the table on Day 30 match how your workers will really be deployed?
