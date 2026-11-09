# Day 15 — Child workflows and parent close policies

[← Week 3](../README.md) · [Day 16 →](../day-16-fan-out/README.md)

**Time:** 60–90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-15/`](../../../solutions/day-15/)

## Why today matters

The orchestrator can see drift. Now it has to do something about it, and two very different jobs
show up. Fixing config drift is a handful of steps on one device: back up, push, verify, roll back
if needed. An EOS upgrade is hours long: wait for the window, install, reload, wait for the box to
come back, compare before and after. Neither belongs inside the orchestrator's loop, and neither is
a single activity.

Today the orchestrator starts a **child workflow** per drift: `ConfigRemediationWorkflow` for
config, `DeviceUpgradeWorkflow` for versions. Each child has its own history, its own retries and
its own ID you can look up. And you decide, per child, what happens to it if the orchestrator is
stopped: that's the **parent close policy**.

## Concept

### Child workflow vs activity

| | Activity | Child workflow |
| --- | --- | --- |
| What it is | One function call that does I/O | A whole workflow, started by another workflow |
| Can contain | Code that talks to devices | Activities, timers, signals, more children |
| History | Inside the parent's history | Its own history, own workflow ID |
| Good for | One step | A multi-step job that's worth tracking on its own |

Use a child when the job has several steps of its own, needs its own ID (so people can find it,
or so only one can exist at a time), or might outlive the parent.

### Start and wait, or start and move on

- `await workflow.execute_child_workflow(...)` starts the child and waits for its result, like an
  activity call.
- `await workflow.start_child_workflow(...)` waits only until the child has **started**, and
  returns a handle. The parent carries on.

Config remediation is quick, so the orchestrator waits for it and records the result. An upgrade
can wait hours for its window, so the orchestrator just starts it and moves on.

### Parent close policies

When a parent workflow closes (completes, fails, is cancelled, terminated, or continues as new)
while a child is still running, the child's **parent close policy** decides what happens to it:

| Policy | The child is... | Here |
| --- | --- | --- |
| `TERMINATE` (the default) | Terminated immediately | — |
| `REQUEST_CANCEL` | Asked to cancel, so it can clean up | Config remediation: don't keep changing a device with nobody watching |
| `ABANDON` | Left alone to finish | Upgrades: never cut an upgrade off halfway |

Network analogy: a change that's halfway through a reload. You don't pull the plug just because
the person who scheduled it went home.

### A child ID is a lock

Child IDs here are `remediate-config-<device>` and `upgrade-<device>`. Temporal allows only one
running workflow per ID, so if the last cycle's upgrade is still going, starting another one fails
with `WorkflowAlreadyStartedError`. Today the orchestrator catches that for upgrades and moves on.
Day 16 is all about using IDs this way.

## Walkthrough

### 1. `models.py`

`RemediationRequest(device, missing_lines, dry_run=True)` and
`RemediationResult(device, ok, pushed_lines, diff, rolled_back, error)` for config;
`UpgradeRequest(device, target_version)` and `UpgradeResult(device, ok, detail)` for upgrades.
`ComplianceState` gains `remediation: str | None`, and `OrchestratorInput` gains:

```python
# file: netops_temporal/models.py
    # Day 15: remediation children only plan (dry run) unless this is turned off (Day 17).
    dry_run: bool = True
```

### 2. `workflows/remediation.py`: plan only, for now

```python
# file: netops_temporal/workflows/remediation.py
@workflow.defn
class ConfigRemediationWorkflow:
    @workflow.run
    async def run(self, req: RemediationRequest) -> RemediationResult:
        diff = "\n".join(f"+{line}" for line in req.missing_lines)
        workflow.logger.info("%s: would add %d line(s)", req.device, len(req.missing_lines))
        return RemediationResult(device=req.device, ok=True, diff=diff)
```

It returns the diff it *would* push and changes nothing. Day 17 makes it push, safely.

### 3. `workflows/upgrade.py`: a stand-in with the real shape

```python
# file: netops_temporal/workflows/upgrade.py
        before = await workflow.execute_activity(
            get_device_facts, FactsRequest(device=req.device), **options
        )
```

```python
# file: netops_temporal/workflows/upgrade.py
        await workflow.sleep(RELOAD_TIME)  # stand-in for "install image, reload, wait"
        after = await workflow.execute_activity(
            get_device_facts, FactsRequest(device=req.device), **options
        )
```

cEOS can't be upgraded in place, so the "reload" is a 60-second timer and the result honestly
says `still on 4.32.0F (cEOS can't be upgraded in place: stand-in)`. The structure (pre-check,
long wait, post-check, compare) is what a real upgrade workflow looks like.

### 4. `workflows/orchestrator.py`: a child per drift

After each cycle:

```python
# file: netops_temporal/workflows/orchestrator.py
            # Day 15: one child workflow per drift, all running in parallel.
            await asyncio.gather(
                *(self.remediate(s, inp.dry_run) for s in results if s.status == "drifted")
            )
```

Config drift: start and wait, with `REQUEST_CANCEL`:

```python
# file: netops_temporal/workflows/orchestrator.py
                result = await workflow.execute_child_workflow(
                    ConfigRemediationWorkflow.run,
                    RemediationRequest(
                        device=drift.device, missing_lines=drift.missing_lines, dry_run=dry_run
                    ),
                    id=f"remediate-config-{drift.device}",
                    # If the orchestrator is cancelled or terminated, ask this child to stop
                    # too: a config change shouldn't run on without anyone watching it.
                    parent_close_policy=ParentClosePolicy.REQUEST_CANCEL,
                )
```

Version drift: start and move on, with `ABANDON`:

```python
# file: netops_temporal/workflows/orchestrator.py
            try:
                await workflow.start_child_workflow(
                    DeviceUpgradeWorkflow.run,
                    UpgradeRequest(device=drift.device, target_version=drift.expected),
                    id=f"upgrade-{drift.device}",
                    parent_close_policy=ParentClosePolicy.ABANDON,
                )
            except WorkflowAlreadyStartedError:
                # The last cycle's upgrade is still running. More on this on Day 16.
                return f"upgrade: upgrade-{drift.device} already running"
            return f"upgrade: started upgrade-{drift.device}"
```

A child that fails raises `ChildWorkflowError` in the parent; `run_child` catches it and records
`"<kind>: failed: ..."`, so one failed remediation doesn't stop the orchestrator.

Both child workflows go into `WORKFLOWS`. The starter's `status` now prints a `->` line with each
device's remediation.

### 5. Testing parent close policies needs a real server

`tests/conftest.py` gains `dev_env` and `dev_worker` fixtures: a real Temporal dev server from
`WorkflowEnvironment.start_local()` (it uses your `temporal` CLI if installed, otherwise downloads
the dev server once). The time-skipping test server doesn't apply parent close policies, so the
"upgrade survives its parent" test runs there. The course found that out the hard way: the test
passed even with `TERMINATE`, until it moved to the real server.

## Run it

Restart the worker, terminate any old `orchestrator`, then:

```bash
uv run --env-file .env python -m netops_temporal.starters.orchestrator start
uv run --env-file .env python -m netops_temporal.starters.orchestrator status
```

Expected:

```
after 1 cycle(s):
  bos-acc-01  drifted   config: 1 missing (want 1 policy line(s) present)
                        -> config: dry run, would add 1 line(s)
  ...
  nyc-acc-01  drifted   version: 4.32.0F (want 4.33.1F); config: 1 missing (want 1 policy line(s) present)
                        -> upgrade: started upgrade-nyc-acc-01; config: dry run, would add 1 line(s)
```

In the UI, the workflow list now shows `remediate-config-*` (completed) and `upgrade-nyc-acc-01`
(running, in its "reload"). Open one: it has its own history, with a link back to its parent. In
the orchestrator's history, **StartChildWorkflowExecutionInitiated** events show each child's ID
and parent close policy.

## Break it

1. **Terminate the parent.** While `upgrade-nyc-acc-01` is still running (within a minute of a
   cycle), `temporal workflow terminate --workflow-id orchestrator`. Then
   `temporal workflow list --query 'WorkflowType="DeviceUpgradeWorkflow" AND ExecutionStatus="Running"'`:
   the upgrade is still running. That's `ABANDON`.
2. **Ask for a second upgrade.** Start the orchestrator again and `force-check` within the minute.
   `status` shows `upgrade: upgrade-nyc-acc-01 already running`: the workflow ID refused a
   duplicate.
3. **Change the policy.** Set the upgrade's policy to `ParentClosePolicy.TERMINATE` and run
   `scripts/test-solutions.sh 15`. `test_upgrade_child_survives_parent_termination` fails: the
   upgrade died with its parent. Put it back.

## Check yourself

1. When would you use a child workflow instead of an activity?
2. What's the difference between `execute_child_workflow` and `start_child_workflow`?
3. Why `REQUEST_CANCEL` for config remediation but `ABANDON` for upgrades?
4. What happens if the orchestrator tries to start `upgrade-nyc-acc-01` while one is running?
5. Why does one test use a real dev server instead of the time-skipping one?

<details>
<summary>Answers</summary>

1. When the job has several steps of its own, deserves its own ID and history, or must be able
   to outlive the caller.
2. `execute_child_workflow` waits for the child's result. `start_child_workflow` returns once the
   child has started, and the parent carries on.
3. A config change shouldn't continue unsupervised if the orchestrator is stopped, but it should
   get the chance to clean up (cancel, not terminate). An upgrade halfway through a reload must
   finish, whatever happens to the parent.
4. The start fails with `WorkflowAlreadyStartedError`, because only one workflow with that ID can
   run at a time. The orchestrator catches it and records "already running".
5. The time-skipping test server doesn't apply parent close policies, so a test there can't tell
   `ABANDON` from `TERMINATE`.

</details>

## Solution

[`solutions/day-15/`](../../../solutions/day-15/): new `workflows/remediation.py` (plan only) and
`workflows/upgrade.py` (stand-in); the orchestrator starts a child per drift; remediation models
in `models.py`; `dev_env`/`dev_worker` fixtures in `tests/conftest.py`. `tests/test_children.py`
checks both children, one child per drift, the recorded parent close policies, the upgrade
surviving its parent (on a real dev server), and the remediation outcome in state.
