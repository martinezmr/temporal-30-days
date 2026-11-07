# Day 09 — Queries

[← Day 08](../day-08-signals/README.md) · [Day 10 →](../day-10-updates/README.md)

## Goal

Ask a running workflow what it knows, without changing it.

## Build

```python
class WatchStatus(BaseModel):
    device: str
    paused: bool
    checks: int
    last_checked: datetime | None
    last_facts: DeviceFacts | None

@workflow.query
def get_status(self) -> WatchStatus:
    return WatchStatus(device=self.device, paused=self.paused, checks=self.checks,
                       last_checked=self.last_checked, last_facts=self.last_facts)
```

Set `self.last_checked = workflow.now()` after each check.

- UI: open the workflow → **Queries** tab → `get_status`.
- CLI: `temporal workflow query --workflow-id watch-bos-rtr-01 --type get_status`
- Python: `await handle.query(DeviceWatchWorkflow.get_status)`

## Gotchas

- Query handlers must not mutate state, await activities, or sleep.
- Queries work on completed workflows too (as long as a worker for that type is running).
- Queries don't appear in history. Signals and updates do.

## Done when

- [ ] A small `starters/status.py` prints the status of every watch workflow (`client.list_workflows('WorkflowType="DeviceWatchWorkflow"')`).
