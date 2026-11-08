# Day 23 — Nexus: handing a long job to another team

[← Day 22](../day-22-nexus-sync/README.md) · [Day 24 →](../day-24-nexus-contracts/README.md)

**Time:** 90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-23/`](../../../solutions/day-23/)

## Why today matters

Yesterday the compliance team took over the policy. Today they take over the fix as well. Their
change-approval rules, their audit trail and their on-call rota all cover config pushes, so they
want the remediation saga (Day 17) running in *their* namespace, on *their* workers. You still
decide when a device needs fixing. They decide how it gets fixed.

A config remediation takes minutes: a backup, a push, a verify, maybe a rollback. That's far too
long for a sync operation, which has to answer within seconds. So today's operation is
**workflow-backed**: the handler starts a workflow in the compliance namespace and hands back a
reference to it, and your orchestrator waits for that workflow's result, however long it takes.

Network analogy: yesterday's question was answered at the service desk counter. Today you raise a
change ticket. The desk gives you a ticket number straight away, the work happens on their side
over the next hour, and you hear back when it's closed. If you withdraw the request, they stop the
work and undo whatever they've already done.

## Concept

### Sync vs workflow-backed operations

| | Sync (Day 22) | Workflow-backed (today) |
| --- | --- | --- |
| Handler | Returns the result | Starts a workflow, returns its handle |
| How long | Seconds | As long as the workflow runs: minutes, days |
| Caller history | Scheduled → Completed | Scheduled → **Started** → Completed |
| In the handler's namespace | Nothing | A workflow you can find, query and inspect |
| Cancel | Nothing to cancel | Cancels the handler's workflow |

From the caller's side the code is identical: `execute_operation(...)` and await the result. The
caller can't tell, and doesn't need to know, whether the result came from a quick lookup or a
saga that ran for an hour.

### How the result gets back

When the handler starts the workflow, Temporal attaches a **callback** to it. When the
remediation workflow closes, the server delivers its result to the orchestrator's history as
**NexusOperationCompleted**. Nothing polls. Both sides can restart their workers in the meantime,
because both the operation and the workflow are durable.

### Cancellation crosses the boundary, termination doesn't

Cancel the orchestrator and its pending operations are cancelled. The server passes the cancel to
the compliance namespace, the remediation workflow is cancelled, and Day 17's saga rolls back
whatever it had pushed. The orchestrator's history shows **NexusOperationCancelRequested**, then
**NexusOperationCanceled**, then **WorkflowExecutionCanceled**.

**Terminate** the orchestrator and nothing reaches the other side: termination doesn't run any
of the workflow's code, so no cancel is ever sent. The remediation runs to the end. (A child
workflow has a parent close policy for this, Day 15. A Nexus operation doesn't: the handler's
workflow belongs to another team.)

### Waiting for every cancellation

Cancellation only works if the orchestrator *waits* for its operations to finish cancelling.
`asyncio.gather` doesn't: when the workflow is cancelled, every gathered task is cancelled, and
gather raises as soon as the *first* one finishes. That's usually a task waiting for a remediation
slot (Day 16), which has nothing to wait for. The workflow then closes while the Nexus operations
are still being cancelled, and their cancel requests are dropped with it. The remediations carry
on and push config.

The children of Days 15–22 hid this: their `REQUEST_CANCEL` parent close policy cancelled them
when the parent closed. Nexus has no parent close policy, so today the orchestrator uses
`gather_all`, a gather that waits for every task before passing the cancellation on.

### Who owns what now

```
 namespace: default                          namespace: compliance
┌──────────────────────────────┐            ┌────────────────────────────────────┐
│ orchestrator                 │            │ compliance worker, compliance-tq   │
│   finds drift                │  remediate │   handler: remediate ─► starts     │
│   execute_operation ─────────┼─► endpoint─┼─► ConfigRemediationWorkflow        │
│   waits for the result  ◄────┼─ callback ─┼─  (Day 17's saga, unchanged)       │
│ upgrades: still children     │            │ device-io worker: its activities   │
└──────────────────────────────┘            └────────────────────────────────────┘
```

The remediation workflow and its activities run on the compliance team's workers now. Its code
hasn't changed. Your main worker still registers it, for orchestrators that started before today
and still start it as a child (the patch, below).

## Walkthrough

### 1. `nexus/service.py`: one more operation in the contract

```python
# file: netops_temporal/nexus/service.py
@nexusrpc.service
class ComplianceService:
    get_policy: nexusrpc.Operation[PolicyRequest, Policy]
    # Day 23: fix a device's config drift. Backed by a workflow, so it can take as long as the
    # saga needs, and survives either side's workers restarting.
    remediate: nexusrpc.Operation[RemediationRequest, RemediationResult]
```

The input and output are the models Day 15's child already used.

### 2. `nexus/handler.py`: start the workflow, return its handle

```python
# file: netops_temporal/nexus/handler.py
@nexus.workflow_run_operation
async def remediate(
    self, ctx: nexus.WorkflowRunOperationContext, req: RemediationRequest
) -> nexus.WorkflowHandle[RemediationResult]:
    try:
        return await ctx.start_workflow(
            ConfigRemediationWorkflow.run,
            req,
            # Day 16's lock, now kept by the team that owns remediation.
            id=f"remediate-config-{req.device}",
            task_queue=COMPLIANCE_TASK_QUEUE,
            search_attributes=TypedSearchAttributes(
                [SearchAttributePair(DEVICE_SA, req.device)]
            ),
            static_summary=f"config remediation for {req.device}",  # (shortened)
        )
    except WorkflowAlreadyStartedError as err:
        # Not worth retrying: fail the operation, with a message the caller can show.
        raise nexusrpc.OperationError(
            f"remediate-config-{req.device} already running",
            state=nexusrpc.OperationErrorState.FAILED,
        ) from err
```

`ctx.start_workflow` is the Nexus version of `client.start_workflow`. It also wires up the
callback, so use it rather than a client of your own.

The workflow ID is still the lock: one remediation per device, whoever asks. When the ID is
taken, the handler raises an **operation error**. That's different from Day 22's handler error:
a handler error says "the request went wrong, maybe retry", and an operation error says "the
request was handled, and the answer is no". It's never retried, and reaches the caller as a
`NexusOperationError` whose cause carries the message.

### 3. `workers/compliance.py`: the compliance team runs the saga

```python
# file: netops_temporal/workers/compliance.py
def compliance_worker(client: Client) -> Worker:
    return Worker(
        client,
        task_queue=COMPLIANCE_TASK_QUEUE,
        nexus_service_handlers=[ComplianceServiceHandler()],
        workflows=[ConfigRemediationWorkflow],
    )


def remediation_activity_worker(client: Client, executor: ThreadPoolExecutor) -> Worker:
    return Worker(
        client,
        task_queue=DEVICE_IO_TASK_QUEUE,
        activities=REMEDIATION_ACTIVITIES,
        activity_executor=executor,
        max_concurrent_activities=MAX_ACTIVITIES,
    )
```

The saga sends its activities to `device-io` (Day 21), so the compliance process runs a device-io
worker too, in its own namespace. Task queues belong to a namespace: `device-io` in `compliance`
and `device-io` in `default` are two different queues.

### 4. `workflows/orchestrator.py`: the call, behind a patch

```python
# file: netops_temporal/workflows/orchestrator.py
async with self.remediation_slots:
    # A Nexus operation instead of a child is a different command, so orchestrators from
    # before keep starting children (Day 19).
    if workflow.patched("remediate-via-nexus"):
        try:
            result = await self.remediate_via_nexus(drift, dry_run)
        except NexusOperationError as err:
            # e.g. "remediate-config-bos-acc-01 already running"
            reason = err.cause.message if err.cause else err.message
            return f"config: {reason}"
    else:
        ...  # Day 16's child, unchanged
```

```python
async def remediate_via_nexus(self, drift: DriftReport, dry_run: bool) -> RemediationResult:
    compliance = workflow.create_nexus_client(
        service=ComplianceService, endpoint=COMPLIANCE_ENDPOINT
    )
    return await compliance.execute_operation(
        ComplianceService.remediate,
        RemediationRequest(
            device=drift.device, missing_lines=drift.missing_lines, dry_run=dry_run
        ),
    )
```

The slot is held while the operation runs, so Day 16's cap still holds: at most two
remediations at once, now across the namespace boundary. Upgrades stay as children: they're
still yours.

And the gather that waits for everything:

```python
async def gather_all(*aws):
    """asyncio.gather, except that a cancellation waits for every task to finish cancelling."""
    tasks = [asyncio.ensure_future(aw) for aw in aws]
    try:
        return await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        await workflow.wait(tasks)  # asyncio.wait, in a deterministic order
        raise
```

`workflow.wait` is the workflow-safe `asyncio.wait`. The SDK warns if you use `asyncio.wait`
inside a workflow, because the order it reports finished tasks in isn't deterministic.

### 5. The tests

`tests/histories/orchestrator_day22.json` is a Day 22 orchestrator's history. It replays only
because of the patch. In `tests/test_nexus.py`:

- `test_remediate_runs_workflow_in_compliance_namespace`: the workflow runs in `compliance`
  (with its device search attribute), and the result comes back to the orchestrator.
- `test_remediation_already_running_fails_operation`: Day 16's lock, across the boundary (Break
  it, 4).
- `test_cancel_orchestrator_cancels_nexus_operation`: three config drifts and two slots. Cancel
  the orchestrator while two remediations are running: both end **Canceled** in the compliance
  namespace, nothing is left pushed, and the orchestrator's history has two
  **NexusOperationCanceled** before **WorkflowExecutionCanceled**.

A few Day 15–16 tests changed with the code: remediations show up as Nexus operations in the
orchestrator's history now, not as children. The tests that need two namespaces, or that count
Nexus operations, use `nexus_env` or `dev_env`: the time-skipping test server doesn't handle
several workflow-backed operations reliably.

## Run it

Terminate any old `orchestrator` and `upgrade-nyc-acc-01`, and start the three terminals from
Day 22 (the endpoint script is safe to run again). Restart the compliance worker: it runs the
remediation workflow and its activities now.

```bash
uv run --env-file .env python -m netops_temporal.starters.orchestrator start
uv run --env-file .env python -m netops_temporal.starters.orchestrator status
```

Dry run: `status` shows the drifted devices with `config: dry run, would add N line(s)`. In the
UI, the orchestrator's history has **NexusOperationScheduled**, **NexusOperationStarted** and
**NexusOperationCompleted** for `remediate`. Switch to the `compliance` namespace: the
`remediate-config-*` workflows are there, with the summary and device search attribute.

```bash
temporal workflow list -n compliance --query 'Device="bos-acc-01"'
```

## Break it

1. **Cancel in the middle.** Mock mode makes this easy to time: restart both workers with
   `MOCK_CLI_DELAY=3`, then `start --apply`. As soon as
   `temporal workflow list -n compliance --query 'ExecutionStatus="Running"'` shows two
   remediations, run `temporal workflow cancel --workflow-id orchestrator`. Both remediations end
   **Canceled**, with `ComplianceStatus="cancelled"`, and the devices are as they were. The
   orchestrator's history ends with the cancel requests, two **NexusOperationCanceled**, and then
   **WorkflowExecutionCanceled**.

   Now change both `gather_all(` calls in the orchestrator back to `asyncio.gather(`, restart the
   worker and do it again (terminate `upgrade-nyc-acc-01` first). The orchestrator is Canceled
   straight after the two **NexusOperationCancelRequested** events, but the remediations complete
   and push their config. Run `test_cancel_orchestrator_cancels_nexus_operation`: it fails the same
   way. Put `gather_all` back.
2. **Terminate instead.** `start --apply` again, and this time
   `temporal workflow terminate --workflow-id orchestrator` while the remediations run. They
   complete and push: termination sends nothing across. To stop them, cancel them in their own
   namespace (`temporal workflow cancel -n compliance --workflow-id remediate-config-bos-acc-01`).
   That's the compliance team's call now, not yours.
3. **Stop the compliance worker mid-remediation.** Ctrl-C it while a remediation runs. The
   remediation stays Running in the compliance namespace, and
   `temporal workflow describe --workflow-id orchestrator -o json` shows its operation as
   `PENDING_NEXUS_OPERATION_STATE_STARTED`: the handler's part is done, so there's nothing to
   retry, and the orchestrator just waits. Start the worker again and the remediation carries on
   where it stopped. Give it a minute: the activity that was running when the worker died is only
   retried once its timeout expires (Day 4). Then `status` shows the pushes.
4. **Hold the lock.** `test_remediation_already_running_fails_operation` plays an operator who
   already holds `remediate-config-bos-acc-01` in the compliance namespace (on a task queue no
   worker polls, so it stays running). The orchestrator's cycle reports
   `config: remediate-config-bos-acc-01 already running`: the handler's operation error reached
   it as a `NexusOperationError`, with no retries and no second remediation. Delete the handler's
   `except WorkflowAlreadyStartedError` branch and run it again: the SDK still fails the
   operation, but with its own `Workflow execution already started` message, which tells an
   operator less. Put it back.

## Check yourself

1. Why is `remediate` workflow-backed, when `get_policy` is sync?
2. How does the remediation's result get back to the orchestrator?
3. What's the difference between a handler error and an operation error?
4. You cancel the orchestrator. What happens in the compliance namespace? What if you terminate
   it instead?
5. Why does the orchestrator need `gather_all` today, when `asyncio.gather` was fine on Day 15?
6. Why does the main worker still register `ConfigRemediationWorkflow`?

<details>
<summary>Answers</summary>

1. A remediation takes minutes and has to survive restarts. A sync operation must answer within
   seconds. A workflow can run for as long as it needs.
2. `ctx.start_workflow` attaches a callback to the workflow. When it closes, the server delivers
   the result to the orchestrator's history as NexusOperationCompleted.
3. A handler error means handling the request failed (it's retried, unless its type says
   otherwise, like `BAD_REQUEST`). An operation error means the request was handled and the
   answer is "failed" (or "cancelled"). It's never retried.
4. Cancel: the operation is cancelled, so the remediation workflow is cancelled and its saga rolls
   back. Terminate: no code runs, no cancel is sent, and the remediation carries on.
5. Plain gather raises as soon as the first task is cancelled, and the workflow closes with
   operations still being cancelled. Those cancels are dropped. Children were cancelled anyway by
   their parent close policy. Nexus operations have none.
6. Orchestrators that started before today replay down the unpatched branch, which still starts
   the remediation as a child on the main worker.

</details>

## Solution

[`solutions/day-23/`](../../../solutions/day-23/): `remediate` in `nexus/service.py` and
`nexus/handler.py`; `workers/compliance.py` runs the remediation workflow and its activities; the
orchestrator's patched `remediate_via_nexus` and `gather_all`. Tests: `tests/test_nexus.py`,
`tests/histories/orchestrator_day22.json`, and Days 15–16 tests updated for Nexus.
