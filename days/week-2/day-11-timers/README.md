# Day 11 — Durable timers and maintenance windows

[← Day 10](../day-10-updates/README.md) · [Day 12 →](../day-12-continue-as-new/README.md)

## Goal

Wait hours or days inside a workflow, reliably, and wake early when something happens.

## Learn

- `await workflow.sleep(timedelta(days=3))` is a server-side timer: it survives worker restarts and deploys.
- `wait_condition(fn, timeout=...)` races a condition against a timer; it raises `asyncio.TimeoutError` on timeout.
- Docs: [Timers](https://docs.temporal.io/develop/python/workflows/timers)

## Build

```python
async def wait_for_maintenance_window(self, tz_offset_hours: int = -5) -> str:
    now = workflow.now() + timedelta(hours=tz_offset_hours)
    window = now.replace(hour=2, minute=0, second=0, microsecond=0)
    if window <= now:
        window += timedelta(days=1)
    try:
        await workflow.wait_condition(lambda: self.emergency_override,
                                      timeout=window - now)
        return "override"
    except asyncio.TimeoutError:
        return "window"
```

(Hard-coded offset is fine for the lab. Pass the device's site timezone from Nautobot later.)

Use it in the Day 10 maintenance flow: accept the request, wait for the window, run the activity.

## Test

```python
async with await WorkflowEnvironment.start_time_skipping() as env:
    ...
    result = await handle.result()   # 22 hours of waiting finishes in milliseconds
```

Then a second test that sends `emergency_override` and asserts the result is `"override"`.

## Break it

Start a workflow waiting for the window. Restart the worker *and* the Temporal container. The timer is still in the UI with the right fire time.

## Done when

- [ ] Both timer tests pass in under a second.
