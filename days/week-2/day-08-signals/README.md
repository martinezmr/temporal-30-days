# Day 08 — Signals

[← Week 1](../../week-1/README.md) · [Day 09 →](../day-09-queries/README.md)

## Goal

A workflow that loops forever and changes behaviour when you tell it to.

## Learn

- `@workflow.signal` methods mutate workflow state. They return nothing.
- `await workflow.wait_condition(lambda: ...)` blocks until state makes the lambda true — the main tool for reacting to signals.
- Signals sent while no worker is running are stored in history and delivered later.

## Build

```python
@workflow.defn
class DeviceWatchWorkflow:
    def __init__(self) -> None:
        self.paused = False
        self.check_requested = False
        self.checks = 0

    @workflow.run
    async def run(self, device: str) -> None:
        while True:
            await workflow.wait_condition(lambda: not self.paused)
            await workflow.execute_activity(get_device_facts, device,
                                            start_to_close_timeout=timedelta(seconds=30))
            self.checks += 1
            self.check_requested = False
            try:
                await workflow.wait_condition(lambda: self.check_requested,
                                              timeout=timedelta(minutes=5))
            except asyncio.TimeoutError:
                pass  # normal: 5 minutes passed

    @workflow.signal
    def pause(self) -> None:
        self.paused = True

    @workflow.signal
    def resume(self) -> None:
        self.paused = False

    @workflow.signal
    def force_check(self) -> None:
        self.check_requested = True
```

Starter: `handle = client.get_workflow_handle("watch-bos-rtr-01"); await handle.signal(DeviceWatchWorkflow.pause)`.

## Break it

- `temporal workflow signal --workflow-id watch-bos-rtr-01 --name pause`
- Stop the worker, send `force_check`, start the worker. The signal is waiting in history.
- Don't worry that `while True` grows history forever — Day 12 fixes it.

## Done when

- [ ] You can pause, resume and force a check from both the CLI and Python.
