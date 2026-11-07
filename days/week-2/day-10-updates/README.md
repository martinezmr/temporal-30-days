# Day 10 — Updates and validators

[← Day 09](../day-09-queries/README.md) · [Day 11 →](../day-11-timers/README.md)

## Goal

Send a request into a running workflow, get an answer back, and reject bad requests before they touch history.

## Learn

- `@workflow.update` = signal + return value. The caller waits for the result.
- `@my_update.validator` runs first; raising rejects the update and **nothing is written to history**.
- **Update-with-start** / **signal-with-start**: "send this to the workflow for device X, starting it if it doesn't exist." The building block of entity workflows (Day 13).

## Build

```python
@workflow.update
async def request_maintenance(self, req: MaintenanceRequest) -> MaintenanceTicket:
    self.maintenance_queue.append(req)
    await workflow.wait_condition(lambda: req.id in self.accepted)
    return MaintenanceTicket(id=req.id, scheduled_for=self.accepted[req.id])

@request_maintenance.validator
def validate_maintenance(self, req: MaintenanceRequest) -> None:
    if req.device != self.device:
        raise ValueError(f"this workflow owns {self.device}, not {req.device}")
    if self.paused:
        raise ValueError("watch is paused")
```

Caller:

```python
ticket = await handle.execute_update(DeviceWatchWorkflow.request_maintenance, req)
```

Update-with-start:

```python
start_op = WithStartWorkflowOperation(
    DeviceWatchWorkflow.run, "bos-rtr-01",
    id="watch-bos-rtr-01", task_queue=ORCHESTRATION_TASK_QUEUE,
    id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
)
ticket = await client.execute_update_with_start_workflow(
    DeviceWatchWorkflow.request_maintenance, req, start_workflow_operation=start_op)
```

Signal-with-start is `client.start_workflow(..., start_signal="force_check")`.

## Break it

- Send an update for the wrong device. It fails at the caller, and the workflow's history has no trace of it.
- Run update-with-start twice. Second call reuses the running workflow.

## Done when

- [ ] You can explain when you'd pick a signal vs an update for a network change request.
