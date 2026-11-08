# Day 30 — Worker versioning and the CI pipeline

[← Day 29](../day-29-assemble-orchestrator/README.md) · [Back to start](../../../README.md)

**Time:** 2 hours · **Needs the cEOS lab?** No, today runs in `LAB_MODE=mock` ·
**Solution:** [`solutions/day-30/`](../../../solutions/day-30/)

## Why today matters

You can now write the system. Today you ship a new version of it while it's running. A workflow
can run for minutes or for months, so when you deploy, some of them are halfway through. Day 19
gave you one answer: patch the code so old histories still replay. Today adds the other: keep the
old build running beside the new one until its workflows have finished.

Network analogy: costing out a router before you change it. Bring the new path up, move traffic
to it, let what's in flight on the old path finish, and only then take the old path down. Tearing
it down early is what drops sessions.

## Concept

### Patching or versioning

| | Patching (Day 19) | Worker versioning (today) |
| --- | --- | --- |
| Where old and new live | One build, with both paths in `if workflow.patched(...)` | Two builds, each with one path |
| A running workflow | Replays on the new code | Stays on its build, if pinned |
| What you run during a rollout | One set of workers | Both sets, until the old one drains |
| Best for | Workflows that outlive any one build | Workflows shorter than your release cycle |

You need both. The orchestrator runs for months, so no old build can wait for it to finish, and
changes to it need patches. A remediation takes minutes, so it can simply finish where it started.

### Pinned or auto-upgrade

Each workflow type declares how it behaves when a new build becomes current:

| Behavior | A running workflow... | Needs patching? | In this course |
| --- | --- | --- | --- |
| `PINNED` | Finishes on the build it started on | No | `ConfigRemediationWorkflow`, `DeviceUpgradeWorkflow`, and every workflow that doesn't say otherwise |
| `AUTO_UPGRADE` | Moves to the current build at its next workflow task | Yes | `NetworkComplianceOrchestrator`, `DeviceEntityWorkflow`, `DeviceWatchWorkflow`, `TroubleshootWorkflow` |

The cost of pinning is that the old workers must stay up until the last pinned workflow finishes.
That's why `TroubleshootWorkflow` auto-upgrades: it can wait a long time for a person, and an old
build shouldn't have to keep running until someone answers.

### A build's life

```
 workers poll with BUILD_ID=v2 ──► the server knows v2
 lab/deploy.sh v2 25           ──► ramping: 25% of new workflows start on v2
 lab/deploy.sh v2              ──► current: all new workflows start on v2
                                   v1 is now draining: its pinned workflows are still running
 last pinned workflow finishes ──► v1 is drained
 stop v1's workers             ──► v1 can be deleted, once the server stops counting its pollers
```

Rolling back is the same command with the old build: `lab/deploy.sh v1`.

## Walkthrough

### 1. `versioning.py`: one switch

`BUILD_ID` turns versioning on. Without it, every worker runs unversioned, exactly as on Days 1–29.

```python
# file: netops_temporal/versioning.py
def deployment_config() -> WorkerDeploymentConfig | None:
    """The deployment config for this process's workers, or None without BUILD_ID."""
    build_id = os.environ.get("BUILD_ID")
    if not build_id:
        return None
    return WorkerDeploymentConfig(
        version=WorkerDeploymentVersion(deployment_name=DEPLOYMENT_NAME, build_id=build_id),
        use_worker_versioning=True,
        # Workflows that don't say otherwise are short: they finish where they started.
        default_versioning_behavior=VersioningBehavior.PINNED,
    )
```

Workflows need one more piece, because the server rejects a workflow task that declares a behavior
from an unversioned worker. So the declaration goes through a helper that only asks for a behavior
when `BUILD_ID` is set:

```python
# file: netops_temporal/versioning.py
def behavior(wanted: VersioningBehavior) -> VersioningBehavior:
    ...
    return wanted if os.environ.get("BUILD_ID") else VersioningBehavior.UNSPECIFIED
```

### 2. The workers and workflows

Every worker gets the same line. A build is every worker in it, in both namespaces:

```python
# file: netops_temporal/workers/orchestration.py
    worker = Worker(
        client,
        task_queue=ORCHESTRATION_TASK_QUEUE,
        workflows=WORKFLOWS,
        deployment_config=deployment_config(),  # Day 30
    )
```

And each long-lived or change-making workflow says what it needs:

```python
# file: netops_temporal/workflows/remediation.py
# Day 30: minutes long, and a config change must not switch code halfway: pinned.
@workflow.defn(versioning_behavior=behavior(VersioningBehavior.PINNED))
class ConfigRemediationWorkflow:
```

```python
# file: netops_temporal/workflows/orchestrator.py
# Day 30: runs for months, so it moves to each new build (and changes to it need patching).
@workflow.defn(versioning_behavior=behavior(VersioningBehavior.AUTO_UPGRADE))
class NetworkComplianceOrchestrator:
```

### 3. `lab/deploy.sh`: the rollout

[`lab/deploy.sh`](../../../lab/deploy.sh) wraps `temporal worker deployment` for both namespaces,
since each has its own copy of the `netops` deployment. It first checks that both have seen the
build. Without that check, it could move `default` to v2, fail on `compliance`, and leave the two
halves of the system on different builds.

### 4. The tests

`tests/test_versioning.py` runs on a real dev server, with both builds in one process:

- `test_workers_unversioned_without_build_id`: no `BUILD_ID`, no deployment.
- `test_pinned_remediation_finishes_on_v1`: the push waits until v2 is current, so v2 always
  arrives in the middle of the saga. The remediation finishes on v1, and the next one runs on v2.
- `test_auto_upgrade_orchestrator_moves_to_v2`: the same running orchestrator carries on with v2.
- `test_troubleshoot_waiting_on_a_person_moves_to_v2`: the rollout happens during the wait for
  approval, and the approved change is applied on v2.

### 5. The pipeline

[`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml) runs on every pull request. The
stage that matters today is the replay test (Day 6), which runs inside `scripts/test-solutions.sh`
and replays every history in `tests/histories/` against the new code. It's the gate for
`AUTO_UPGRADE` workflows: if it fails, running workflows wouldn't survive the move to your new build.

It has two limits:

- **It only covers workflows with a recorded history.** The orchestrator and the watch have one, but
  `DeviceEntityWorkflow` and `TroubleshootWorkflow` don't, so nothing stops a breaking change to them
  here. Before you rely on this gate in production, record a history for every auto-upgrade workflow.
- **It doesn't know about pinning.** Change `ConfigRemediationWorkflow` and its recorded history
  fails, even though running remediations would stay on the old build. If nothing running needs the
  new code, record a new history instead of patching.

A full pipeline adds two stages this course doesn't run, because it has no registry or shared
environment:

1. Build the worker image, tagged with the commit, and start it with `BUILD_ID` set to that commit.
2. Once its workers are polling, ramp to it and make it current, as `lab/deploy.sh` does.

### 6. How this maps to your production workers

| Here | In production |
| --- | --- |
| `BUILD_ID=v2` on the command line | The commit, set in the image or deployment config |
| Two terminals per build | Old and new worker deployments, both running during the rollout |
| `lab/deploy.sh v2 25`, then `lab/deploy.sh v2` | The same two commands in a pipeline stage, with a check between them |
| You watch `draining`, then stop v1 | Automation that scales the old build down once it's `drained` |

On Kubernetes, the [Temporal Worker Controller](https://docs.temporal.io/production-deployment/worker-deployments/kubernetes-controller)
is built to do that last row. This course doesn't use it, so test it on your platform first.

## Run it

Both builds run the same code today, because the server only cares about the build ID. In real use,
v2 would be your next commit. The server must know `compliance` too, and it does if you've run
`lab/nexus-endpoint.sh` (Day 22).

### 1. Start v1 and make it current

In two terminals, with a 20-second delay on every mock device command so you have time to look:

```bash
BUILD_ID=v1 MOCK_CLI_DELAY=20 LAB_MODE=mock uv run --env-file .env python -m netops_temporal.workers.main
BUILD_ID=v1 MOCK_CLI_DELAY=20 LAB_MODE=mock uv run --env-file .env python -m netops_temporal.workers.compliance
```

Then:

```bash
lab/deploy.sh v1
uv run --env-file .env python -m netops_temporal.starters.orchestrator start
temporal workflow start --namespace compliance --task-queue compliance-tq \
  --type ConfigRemediationWorkflow --workflow-id remediate-demo \
  --input '{"device": "bos-acc-01", "missing_lines": ["ntp server 192.0.2.10"], "dry_run": false}'
temporal workflow describe --namespace compliance -w remediate-demo
```

```
  Behavior        Pinned
  DeploymentName  netops
  BuildId         v1
```

### 2. Start v2 and roll out

In two more terminals, without the delay:

```bash
BUILD_ID=v2 LAB_MODE=mock uv run --env-file .env python -m netops_temporal.workers.main
BUILD_ID=v2 LAB_MODE=mock uv run --env-file .env python -m netops_temporal.workers.compliance
```

Ramp first, then make it current:

```bash
lab/deploy.sh v2 25
lab/deploy.sh v2
lab/deploy.sh status
```

```
Version Summaries:
  DeploymentName  BuildID  DrainageStatus
  netops          v2       unspecified
  netops          v1       draining
```

The ramp is a share of new workflows, so it's only roughly that percentage. In testing, 100 new
remediations at 25% gave 28 on v2 and 72 on v1. With v2 current, 100 out of 100 ran on v2.

### 3. Watch each workflow go its own way

`remediate-demo` is still running on v1, and finishes there. Describe it again once its status is
`COMPLETED`: it still says `BuildId v1`. Start another with `--workflow-id remediate-demo-2` and
`bos-rtr-01`, and that one says `BuildId v2`.

The orchestrator went the other way. `force-check` it, then:

```bash
temporal workflow describe -w orchestrator
```

```
  Behavior        AutoUpgrade
  DeploymentName  netops
  BuildId         v2
```

Same workflow ID, same run, new build.

## Break it

For 1 and 2, keep all four workers running and get two pinned remediations onto v1 while v2 is
current. Roll back, start `remediate-demo-3` and `remediate-demo-4` the same way as `remediate-demo`,
and roll forward again. You have about 40 seconds before they finish, so have the next command ready:

```bash
lab/deploy.sh v1
# ... the two `temporal workflow start` commands ...
lab/deploy.sh v2
```

1. **Retire v1 while a pinned workflow is running.**

   ```bash
   temporal worker deployment delete-version --namespace compliance \
     --deployment-name netops --build-id v1
   ```

   ```
   version 'netops:v1' cannot be deleted since it is draining
   ```

2. **Stop v1's workers anyway.** `kill -9` both v1 processes. The server can't stop you doing this.
   The remediation stays `RUNNING` on v1, and v2's workers don't touch it. In testing, it was still
   there a minute later. Delete is still refused, and `--skip-drainage` doesn't help yet:

   ```
   version 'netops:v1' cannot be deleted since it has active pollers
   ```

   There are two ways out:

   - **Start v1's workers again.** The remediation carries on and finishes on v1. This is the safe
     answer, and the reason to keep old images until a build has drained.
   - **Move the workflow to v2 yourself.** v2 must be able to replay its history, which is exactly
     what pinning let you avoid checking, so treat this as a last resort:

     ```bash
     temporal workflow update-options --namespace compliance -w remediate-demo-4 \
       --versioning-override-behavior pinned \
       --versioning-override-deployment-name netops --versioning-override-build-id v2
     ```

     Its history then shows workflow tasks completed on `v1`, then on `v2`.

3. **Retire v1 properly.** With nothing pinned to it, v1 turned `drained` about a minute after the
   last remediation finished. Delete it with its workers still up, and you get `has active pollers`
   again. Stop them and keep trying: in testing, the delete succeeded about five minutes later,
   once the server stopped counting those pollers.

4. **Roll out half a build.** Start a v3 `workers.main`, but not `workers.compliance`, then run
   `lab/deploy.sh v3`:

   ```
   compliance has never seen build v3: start its workers with BUILD_ID=v3. Nothing changed.
   ```

   If a build polls only some of the current version's task queues in a namespace, the server
   refuses too, with `missing active task queues`. Its workers are probably still starting, so try
   again.

5. **Skip the patch on an auto-upgrade workflow.** In `workflows/orchestrator.py`, remove the
   `timeout=` from the approval wait, then run the replay test:

   ```bash
   uv run pytest tests/test_testing_layers.py -q
   ```

   `test_replay_committed_histories[orchestrator_cycle]` fails with `TMPRL1100`. That's the pipeline
   stopping a build that running orchestrators couldn't have survived. Put the line back.

## Check yourself

1. Why is the orchestrator auto-upgrade and the remediation pinned?
2. You make v2 current. Which workflows start on it, and what happens to a remediation already
   running on v1?
3. Your new build changes the orchestrator's activity order. Does worker versioning save you?
4. A pinned workflow has been running on v1 for a week, and you want to retire v1. What are your
   options, and which do you try first?
5. What does the replay test protect in a pipeline, and which workflows does it matter most for?

<details>
<summary>Answers</summary>

1. The orchestrator runs for months, so pinning it would keep an old build alive forever. A
   remediation takes minutes and changes a device, so it should finish on the code that started it.
2. All new workflows start on v2. The remediation finishes on v1, and v1 stays `draining` until it
   does. Auto-upgrade workflows move to v2 at their next workflow task.
3. No. It's auto-upgrade, so it replays its history on the new code. You need a patch (Day 19), and
   the replay test should catch you if you forget.
4. First find out why it's still running, and let it finish on v1 if you can. Otherwise, cancel it
   so its saga undoes what it did, or as a last resort override it to v2, once you've confirmed v2
   can replay its history.
5. It proves the new code can replay real histories, so running workflows survive the deployment.
   It matters most for auto-upgrade workflows, since pinned ones never replay on the new build.

</details>

## You finished the month

That's the course: durable execution from a first workflow to a versioned, reviewed, agent-assisted
compliance system. Write your own summary in [`LEARNING.md`](../../../LEARNING.md) while it's fresh.
[`docs/feature-checklist.md`](../../../docs/feature-checklist.md) lists what to explore next.

## Solution

[`solutions/day-30/`](../../../solutions/day-30/): new `versioning.py`; `deployment_config()` on
every worker in `workers/` and in `tests/conftest.py`; `versioning_behavior` on the orchestrator,
entity, watch, troubleshoot, remediation and upgrade workflows. Tests: new
`tests/test_versioning.py`. Also
[`lab/deploy.sh`](../../../lab/deploy.sh) and the replay comment in
[`ci.yml`](../../../.github/workflows/ci.yml).
