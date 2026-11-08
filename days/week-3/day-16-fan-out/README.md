# Day 16 — Workflow IDs as locks, and bounded fan-out

[← Day 15](../day-15-child-workflows/README.md) · [Day 17 →](../day-17-saga-rollback/README.md)

**Time:** 60 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-16/`](../../../solutions/day-16/)

## Why today matters

Two things go wrong when automation starts changing devices at scale:

- **Duplicates.** The same drift is seen twice (by two cycles, or by the orchestrator and an
  operator who's fixing it by hand), and two remediations hit one device at once.
- **Too much at once.** 400 devices drift after a policy change, and the automation pushes to all
  of them in the same minute. If the change is wrong, it's wrong everywhere before anyone notices.

Today you fix both, with two small tools: the **workflow ID** as a lock, and a **semaphore**
inside the workflow to cap how many remediations run at once.

## Concept

### Only one running workflow per ID

Temporal guarantees that at most one workflow with a given ID is running in a namespace. Starting
a second one fails. That makes a well-chosen ID a distributed lock, with no database or lock file:

- `remediate-config-bos-acc-01`: at most one config remediation per device.
- `upgrade-nyc-acc-01`: at most one upgrade per device.

It doesn't matter who starts it: the orchestrator, an operator with the CLI, another workflow.

For **child** workflows, a start with a taken ID raises `WorkflowAlreadyStartedError` in the
parent. (Client starts have more options: `id_conflict_policy` can say "use the existing one"
instead of failing, which is what update-with-start used on Day 10. Child workflow starts don't
have that option in the Python SDK, so the orchestrator catches the error.)

### ID reuse vs ID conflict

Two different questions, with two different settings:

| Question | Setting | Example |
| --- | --- | --- |
| A workflow with this ID is **running**. Start another? | ID conflict policy | `USE_EXISTING` (Day 10), or fail (the default) |
| One with this ID **has finished**. Allow a new one? | ID reuse policy | `ALLOW_DUPLICATE` (the default): yes, the next remediation can reuse the ID |

The defaults are what the orchestrator wants: never two at once, but tomorrow's remediation can
use the same ID.

### Bounded fan-out with a semaphore

`asyncio.Semaphore(n)` works inside a workflow just like `asyncio.Lock` did on Day 13: Temporal's
event loop is deterministic, so the same remediations get the slots in the same order on every
replay. Wrapping each config child in `async with self.remediation_slots:` means at most `n` are
running; the rest wait for a slot.

Network analogy: a change policy that says "no more than two sites at a time".

## Walkthrough

### 1. `models.py`

```python
# file: netops_temporal/models.py
    # Day 16: never remediate more than this many devices at once.
    max_parallel_remediations: int = 2
```

### 2. `workflows/orchestrator.py`: the semaphore

```python
# file: netops_temporal/workflows/orchestrator.py
        # Day 16: asyncio.Semaphore works in workflows like asyncio.Lock (Day 13): at most
        # this many config remediations hold a slot at the same time.
        self.remediation_slots = asyncio.Semaphore(inp.max_parallel_remediations)
```

### 3. A slot, and the ID as a lock

```python
# file: netops_temporal/workflows/orchestrator.py
            if drift.kind == "config":
                async with self.remediation_slots:
                    try:
                        result = await workflow.execute_child_workflow(
                            ConfigRemediationWorkflow.run,
                            RemediationRequest(
                                device=drift.device,
                                missing_lines=drift.missing_lines,
                                dry_run=dry_run,
                            ),
                            # The ID is the lock: only one running remediation per device.
                            id=f"remediate-config-{drift.device}",
                            # If the orchestrator is cancelled or terminated, ask this child to
                            # stop too: a config change shouldn't run on unsupervised.
                            parent_close_policy=ParentClosePolicy.REQUEST_CANCEL,
                        )
                    except WorkflowAlreadyStartedError:
                        # Someone (an operator, or a previous orchestrator) is already
                        # remediating this device. Don't start a second one.
                        return f"config: remediate-config-{drift.device} already running"
```

Upgrades already caught `WorkflowAlreadyStartedError` on Day 15. They aren't counted by the
semaphore, because the orchestrator only starts them and doesn't wait.

### 4. Testing it

- `test_no_more_than_two_remediations_at_once` walks the orchestrator's history and counts child
  workflows that were started but not yet closed. The peak must be exactly 2.
- `test_duplicate_drift_does_not_start_second_remediation` first starts a
  `remediate-config-bos-acc-01` with `start_delay=timedelta(hours=1)`: the workflow exists, and
  holds the ID, but doesn't run yet. That's "an operator scheduled a fix for later". Then one
  orchestrator cycle must report `already running` for that device.

## Run it

Restart the worker and terminate any old `orchestrator`. Play the operator: schedule a
remediation for `bos-acc-01` an hour from now with the CLI:

```bash
temporal workflow start --type ConfigRemediationWorkflow --task-queue netops-orchestration \
  --workflow-id remediate-config-bos-acc-01 \
  --input '{"device": "bos-acc-01", "missing_lines": ["ntp server 192.0.2.10"]}' \
  --start-delay 1h
```

Then start the orchestrator and check the status:

```bash
uv run --env-file .env python -m netops_temporal.starters.orchestrator start
uv run --env-file .env python -m netops_temporal.starters.orchestrator status
```

Expected:

```
  bos-acc-01  drifted   config: 1 missing (want 1 policy line(s) present)
                        -> config: remediate-config-bos-acc-01 already running
  bos-rtr-01  drifted   config: 2 missing (want 2 policy line(s) present)
                        -> config: dry run, would add 2 line(s)
```

Open the orchestrator in the UI and look at the **Timeline**: the config children run at most two
at a time. Terminate `remediate-config-bos-acc-01` when you're done.

## Break it

1. **Remove the semaphore.** Replace `async with self.remediation_slots:` with `if True:` and run
   `scripts/test-solutions.sh 16`. `test_no_more_than_two_remediations_at_once` fails: all four
   children started at once. Put it back.
2. **Set the limit to 1.** Start the orchestrator with `OrchestratorInput(max_parallel_remediations=1)`
   (edit the starter). The **Timeline** shows the config children strictly one after another.
3. **Steal an upgrade's ID.** While no upgrade is running, start any workflow with the ID
   `upgrade-nyc-acc-01` (for example, the `temporal workflow start` command above with that ID and
   `--start-delay 1h`), then `force-check`. The status says
   `upgrade: upgrade-nyc-acc-01 already running`: it's the ID that counts, not the workflow type.

## Check yourself

1. What does Temporal guarantee about workflow IDs, and how does that make a lock?
2. What's the difference between the ID conflict policy and the ID reuse policy?
3. Why is `asyncio.Semaphore` safe inside a workflow?
4. Why doesn't the semaphore cover upgrades?
5. Why does the duplicate test use `start_delay`?

<details>
<summary>Answers</summary>

1. At most one workflow with a given ID runs at a time in a namespace. If every remediation of a
   device uses the same ID, a second one can't start while the first runs, whoever starts it.
2. Conflict: what to do when a workflow with that ID is *running*. Reuse: whether a new workflow
   may use the ID of one that has *finished*.
3. Workflow code runs on Temporal's deterministic event loop, so slots are handed out in the same
   order on every replay.
4. The orchestrator only starts upgrades and moves on, so an upgrade wouldn't hold a slot for its
   duration anyway. Limiting upgrades would need a different approach (for example, the
   orchestrator tracking how many it has running).
5. To have a workflow that holds the ID but isn't doing anything yet, like an operator's
   scheduled fix, so the test is about the ID, not timing.

</details>

## Solution

[`solutions/day-16/`](../../../solutions/day-16/): `max_parallel_remediations` in `models.py`;
a semaphore and `WorkflowAlreadyStartedError` handling for config children in
`workflows/orchestrator.py`. `tests/test_fan_out.py` checks the peak of two (and one, when
configured) and that a taken ID stops a duplicate remediation.
