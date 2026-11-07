# Day 12 — Continue-As-New

[← Day 11](../day-11-timers/README.md) · [Day 13 →](../day-13-entity-workflows/README.md)

## Goal

A workflow that can run forever without its history growing forever.

## Learn

- History is capped (about 51,200 events or 50 MB) and long histories make replay slow.
- `workflow.continue_as_new(state)` ends this run and starts a fresh one with the same workflow ID and the state you pass.
- `workflow.info().is_continue_as_new_suggested()` — the server tells you when it's time.
- Wait for in-flight signal/update handlers first: `await workflow.wait_condition(workflow.all_handlers_finished)`.
- Docs: [Continue-As-New](https://docs.temporal.io/develop/python/workflows/continue-as-new)

## Build

```python
class WatchInput(BaseModel):
    device: str
    checks: int = 0
    paused: bool = False
    last_facts: DeviceFacts | None = None

@workflow.run
async def run(self, inp: WatchInput) -> None:
    self.restore(inp)
    for _ in range(MAX_LOOPS_PER_RUN):          # 3 for today's experiment, ~100 later
        await self.one_cycle()
        if workflow.info().is_continue_as_new_suggested():
            break
    await workflow.wait_condition(workflow.all_handlers_finished)
    workflow.continue_as_new(self.snapshot())
```

## Break it

- Set `MAX_LOOPS_PER_RUN = 3`. Watch the chain of runs under one workflow ID in the UI (Run ID changes, Workflow ID doesn't).
- Query `get_status` across a continue-as-new boundary. State carries over.
- Send a signal right as it continues. It lands in the new run.

## Done when

- [ ] `DeviceWatchWorkflow` takes a single input model and continues-as-new safely.
