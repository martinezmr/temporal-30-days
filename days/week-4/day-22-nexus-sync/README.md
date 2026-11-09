# Day 22 — Nexus: calling another team's service

[← Week 3](../../week-3/README.md) · [Day 23 →](../day-23-nexus-async/README.md)

**Time:** 90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-22/`](../../../solutions/day-22/)

## Why today matters

The compliance policy (which lines every device must have) lives in `policies.py`, in your
repository. But you don't own it: the security and compliance team does. Today, when they want a
new NTP server, they open a ticket and wait for your next deploy. And if they wanted the policy to
come from their own system, they'd have to change your code.

The fix is a **boundary**. The compliance team runs their own service, in their own namespace,
with their own workers and deploys. You call it by name, and you know only its contract: "give me
the policy for role X". That's **Nexus**: Temporal's way for one team's workflows to call another
team's operations, durably, across namespaces.

Network analogy: a service desk with a published catalogue. You pick an item from the catalogue
(the operation), fill in the form (the input), and get a result. Who works the ticket, and how,
is the desk's business.

## Concept

### The pieces

```
 namespace: default                         namespace: compliance
┌───────────────────────────┐              ┌──────────────────────────────┐
│ NetworkComplianceOrchestr.│              │ compliance worker            │
│   nexus client ───────────┼─► endpoint ─►│   task queue compliance-tq   │
│   (service + endpoint)    │  "compliance │   ComplianceServiceHandler   │
└───────────────────────────┘   -endpoint" │     get_policy               │
                                           └──────────────────────────────┘
```

| Piece | What it is | Here |
| --- | --- | --- |
| **Service contract** | Operation names, input and output types. Both sides import it. | `nexus/service.py`: `ComplianceService.get_policy` |
| **Handler** | The code behind each operation, on the owning team's worker | `nexus/handler.py` |
| **Endpoint** | A name the server routes to a namespace + task queue | `compliance-endpoint` → `compliance` / `compliance-tq` |
| **Caller** | A workflow with a Nexus client for a service and an endpoint | the shared compliance cycle |

The caller knows only the endpoint name and the contract. The compliance team can move their
worker, rename their task queue (and update the endpoint), or rewrite the handler, and no caller
changes.

### Sync operations

An operation can be **sync**: the handler answers inside the request, within a few seconds.
`get_policy` looks up a policy and returns it, so it's sync. (Day 23 adds an operation that
starts a whole workflow and can take as long as it needs.)

### What the caller sees

In the caller's history, a Nexus call looks like an activity call:
**NexusOperationScheduled** (endpoint, service, operation, input), then
**NexusOperationCompleted** (the result). Replay uses the recorded result, just like an
activity's.

If the handler's worker is down, the server keeps retrying the operation, and the caller waits;
nothing fails. When the worker comes back, the operation runs and the caller carries on.

### A Nexus call is a new command

Reading `POLICIES` was plain code. Calling Nexus is a command, recorded in history. So this is a
Day 19 change: orchestrators and audits that started before it must replay without Nexus events.
The call is behind `workflow.patched("policy-from-nexus")`, and the Day 19 audit history in
`tests/histories/` checks it.

## Walkthrough

### 1. `nexus/service.py`: the contract

```python
# file: netops_temporal/nexus/service.py
@nexusrpc.service
class ComplianceService:
    get_policy: nexusrpc.Operation[PolicyRequest, Policy]
```

`PolicyRequest(role)` and `Policy(role, required_lines)` are new models in `models.py`.

### 2. `nexus/handler.py`: the compliance team's code

```python
# file: netops_temporal/nexus/handler.py
@service_handler(service=ComplianceService)
class ComplianceServiceHandler:
    # A sync operation answers straight away, inside the Nexus request (a few seconds at most).
    @sync_operation
    async def get_policy(self, ctx: StartOperationContext, req: PolicyRequest) -> Policy:
        if req.role not in POLICIES:
            # The caller sent something wrong: fail now, don't retry.
            raise nexusrpc.HandlerError(
                f"no policy for role {req.role!r}", type=nexusrpc.HandlerErrorType.BAD_REQUEST
            )
        return Policy(role=req.role, required_lines=POLICIES[req.role])
```

The handler still reads `POLICIES` today. The point is *where* it runs: on the compliance team's
worker, so tomorrow it can read their database instead, and nobody else changes anything.

### 3. `workers/compliance.py`: their worker, their namespace

```python
# file: netops_temporal/workers/compliance.py
def compliance_worker(client: Client) -> Worker:
    """The Nexus service handler, on the task queue the endpoint points at."""
    return Worker(
        client,
        task_queue=COMPLIANCE_TASK_QUEUE,
        nexus_service_handlers=[ComplianceServiceHandler()],
    )
```

It connects with `connect(namespace=COMPLIANCE_NAMESPACE)`: `connect()` takes a namespace now.
It isn't part of `workers/main.py` on purpose. It's another team's process.

### 4. `workflows/compliance_cycle.py`: the call

```python
# file: netops_temporal/workflows/compliance_cycle.py
async def policy_for(role: str) -> list[str]:
    """Day 22: the compliance team owns the policy now, behind their Nexus service."""
    # A Nexus operation is a new command. Orchestrators and audits that started before this
    # change have no Nexus events in their history, so they keep reading POLICIES (Day 19).
    if not workflow.patched("policy-from-nexus"):
        return POLICIES[role]
    compliance = workflow.create_nexus_client(
        service=ComplianceService, endpoint=COMPLIANCE_ENDPOINT
    )
    policy = await compliance.execute_operation(
        ComplianceService.get_policy, PolicyRequest(role=role)
    )
    return policy.required_lines
```

`check_device` calls `policy_for(intent.role)`, and treats a failed Nexus operation
(`NexusOperationError`) like a failed activity: the device becomes `unknown`. Both the
orchestrator and the nightly audit use this cycle, so both get the policy from the compliance
team.

### 5. `lab/nexus-endpoint.sh` and the tests

The script creates the endpoint (and the `compliance` namespace, with Day 20's search
attributes, if your dev server doesn't have it yet). It's safe to run again.

In tests, every test server gets a `compliance-endpoint`, and the shared workers include the
compliance worker. `nexus_env` is a real dev server with both namespaces, like the lab, and
`test_get_policy_via_nexus` checks the orchestrator's history has a `get_policy` operation on
`compliance-endpoint` and the right drift.

## Run it

```bash
./lab/nexus-endpoint.sh
```

Three terminals now: the dev worker, the compliance team's worker, and your commands.

```bash
uv run --env-file .env python -m netops_temporal.workers.main
uv run --env-file .env python -m netops_temporal.workers.compliance
```

Terminate any old `orchestrator` and `upgrade-nyc-acc-01`, then `starters.orchestrator start`
and `status`: the same drift as before. The difference is in the history. Open `orchestrator` in
the UI: four **NexusOperationScheduled** events (one per device; click one to see endpoint
`compliance-endpoint`, service `ComplianceService`, operation `get_policy`), and their
**NexusOperationCompleted** results. Switch the UI to the `compliance` namespace (top left):
there's no workflow there. A sync operation runs in the handler, not as a workflow.

## Break it

1. **Stop the compliance worker.** Ctrl-C it, then `force-check`. `status` still shows the last
   cycle. `temporal workflow describe --workflow-id orchestrator` lists
   `Pending Nexus Operations: 4`. In JSON (`-o json`), each is a `get_policy`, with an `attempt`
   count and `lastAttemptFailure: upstream timeout`. Start the compliance worker again: within
   about a minute (the retry backoff) the operations complete and the cycle finishes.
2. **Delete the endpoint.** `temporal operator nexus endpoint delete --name compliance-endpoint`,
   then `force-check`. This one is different: the orchestrator's workflow task fails with
   `BadScheduleNexusOperationAttributes: endpoint "compliance-endpoint" not found`, and even
   `status` fails (`Unable to query workflow due to Workflow Task in failed state`). The workflow
   isn't lost: run `./lab/nexus-endpoint.sh` and within seconds it carries on, and `status`
   works again.
3. **Ask for a role that doesn't exist.** `test_unknown_role_fails_without_retry` has a small
   workflow ask for `PolicyRequest(role="firewall")`. The handler's `BAD_REQUEST` error fails the
   operation straight away, with no retries, and the caller gets a `NexusOperationError` whose
   cause is the handler's message. Change `BAD_REQUEST` to `INTERNAL` and run that test: now the
   server retries the operation over and over, and the test never finishes (Ctrl-C it). Put it
   back. A handler error's type decides whether retrying makes sense.

## Check yourself

1. What does the orchestrator know about the compliance team's service, and what doesn't it know?
2. What's an endpoint, and why do callers use it instead of a namespace and task queue?
3. Why is the Nexus call behind `workflow.patched()`?
4. What happens to the orchestrator when the compliance worker is down? When the endpoint is
   missing?
5. Why does a sync operation leave no workflow in the `compliance` namespace?

<details>
<summary>Answers</summary>

1. It knows the contract (operation names and types) and the endpoint name. It doesn't know the
   namespace, task queue, worker or how the handler works.
2. A name the server maps to a namespace and task queue. The owning team can change where it
   points without any caller changing code.
3. It adds a command. Orchestrators and audits that started before the change have no Nexus
   events in their history and must still replay.
4. Worker down: the server retries the operation and the orchestrator waits, then carries on.
   Endpoint missing: the orchestrator's workflow task fails (and is retried) until the endpoint
   exists again. Either way, nothing is lost.
5. The handler answers inside the request. Day 23's workflow-backed operation starts a workflow.

</details>

## Solution

[`solutions/day-22/`](../../../solutions/day-22/): new `nexus/service.py`, `nexus/handler.py` and
`workers/compliance.py`; `PolicyRequest` and `Policy` in `models.py`; the patched Nexus call in
`workflows/compliance_cycle.py`; the compliance namespace, task queue and endpoint names in
`constants.py`; `connect(namespace=...)`. Outside the solution: `lab/nexus-endpoint.sh`. Tests:
`tests/test_nexus.py`, and endpoint and compliance-worker fixtures in `tests/conftest.py`.
