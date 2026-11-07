# Day 05 — Blocking libraries, heartbeats, cancellation

[← Day 04](../day-04-determinism/README.md) · [Day 06 →](../day-06-testing/README.md)

## Goal

Use blocking network libraries safely, and make long activities resumable.

## Learn

- `async def` activities must never block the event loop. Blocking libraries (pyeapi, netmiko, napalm) go in **sync** activities with an `activity_executor`.
- **Heartbeat**: a long activity reports progress with `activity.heartbeat(details)`. If heartbeats stop for `heartbeat_timeout`, the attempt is failed and retried, and the next attempt reads `activity.info().heartbeat_details`.
- Heartbeats are also how an activity learns it was **cancelled**.
- Docs: [Sync vs async](https://docs.temporal.io/develop/python/best-practices/python-sdk-sync-vs-async) · [Cancellation](https://docs.temporal.io/develop/python/workflows/cancellation)

## Build

1. A sync activity with a blocking library:

    ```python
    @activity.defn
    def get_lldp_neighbors(device: str) -> list[dict]:
        node = pyeapi.connect(host=DEVICE_HOSTS[device], username=..., password=..., transport="https")
        return node.execute(["show lldp neighbors"])["result"][0]["lldpNeighbors"]
    ```

    Worker: `Worker(..., activity_executor=ThreadPoolExecutor(max_workers=10))`.

2. `collect_show_tech(device)` that runs 10 slow commands one by one, heartbeating after each:

    ```python
    start = activity.info().heartbeat_details[0] if activity.info().heartbeat_details else 0
    for i, cmd in enumerate(COMMANDS[start:], start=start):
        output.append(run(cmd))
        activity.heartbeat(i + 1)
    ```

    Call it with `heartbeat_timeout=timedelta(seconds=15)`.

## Break it

- Kill the worker during `collect_show_tech`. Restart it. The next attempt resumes at the last heartbeat, not at command 1.
- Cancel the workflow from the UI during the activity. Catch `asyncio.CancelledError` (async) or check `activity.is_cancelled()` (sync) and clean up.

## Done when

- [ ] You know which of your activities are async vs sync and why.
- [ ] You've watched a heartbeat timeout fire and an attempt resume.
