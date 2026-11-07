# Day 13 — The entity workflow pattern

[← Day 12](../day-12-continue-as-new/README.md) · [Day 14 →](../day-14-orchestrator-v0/README.md)

## Goal

One long-lived workflow per device that is the single owner of that device's changes.

## Learn

- **Entity workflow:** the workflow ID *is* the thing's name (`device-bos-rtr-01`). Temporal guarantees one running workflow per ID, so you get a per-device lock for free.
- Requests arrive as signals/updates and are appended to a queue; the main loop drains it one at a time. Handlers stay tiny.
- Use `asyncio.Lock()` (safe in workflows) if two handlers might run activities at the same time.

## Build

`workflows/device_entity.py`:

```python
@workflow.defn
class DeviceEntityWorkflow:
    def __init__(self) -> None:
        self.queue: list[DeviceRequest] = []
        self.results: dict[str, RequestResult] = {}

    @workflow.run
    async def run(self, inp: DeviceEntityInput) -> None:
        self.restore(inp)
        while not workflow.info().is_continue_as_new_suggested():
            try:
                await workflow.wait_condition(lambda: bool(self.queue), timeout=timedelta(hours=1))
            except asyncio.TimeoutError:
                break  # idle for an hour: continue-as-new to keep history short
            req = self.queue.pop(0)
            self.results[req.id] = await self.handle(req)   # one at a time
        await workflow.wait_condition(workflow.all_handlers_finished)
        workflow.continue_as_new(self.snapshot())

    @workflow.update
    async def submit(self, req: DeviceRequest) -> RequestResult:
        self.queue.append(req)
        await workflow.wait_condition(lambda: req.id in self.results)
        return self.results.pop(req.id)
```

Callers always use update-with-start (Day 10), so they never care whether the entity is running.

## Break it

Fire 10 `submit` calls concurrently with `asyncio.gather` from a starter. Confirm in history that the activities run strictly one after another.

## Done when

- [ ] You can explain why two operators can't push conflicting changes to the same device with this design.
