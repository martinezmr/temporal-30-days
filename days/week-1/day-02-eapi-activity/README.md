# Day 02 — First real activity: facts over eAPI

[← Day 01](../day-01-lab-up/README.md) · [Day 03 →](../day-03-models-and-failures/README.md)

## Goal

A workflow that gets `show version` from a cEOS node, and survives the node going away.

## Learn

- Four activity timeouts: **start-to-close** (one attempt), **schedule-to-close** (all attempts), **schedule-to-start** (waiting in queue), **heartbeat** (Day 5). Always set start-to-close.
- The default retry policy retries forever with exponential backoff. Decide your own.
- Docs: [Activity timeouts](https://docs.temporal.io/develop/python/activities/timeouts) · [Activity execution](https://docs.temporal.io/develop/python/activities/execution)

## Build

1. `activities/eapi.py`: a small async eAPI client (niquests, JSON-RPC `runCmds`) and an activity:

    ```python
    @activity.defn
    async def get_device_facts(device: str) -> dict:
        host = DEVICE_HOSTS[device]
        result = await run_commands(host, ["show version"])
        v = result[0]
        return {"device": device, "model": v["modelName"], "version": v["version"]}
    ```

2. `workflows/facts.py`: `GetFactsWorkflow` calling it with:

    ```python
    await workflow.execute_activity(
        get_device_facts, device,
        start_to_close_timeout=timedelta(seconds=30),
        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2),
                                 backoff_coefficient=2.0, maximum_attempts=5),
    )
    ```

3. Register both in `workers/main.py`; add `starters/facts.py`.
4. Start the habit now: `activities/eapi_mock.py` returning a canned `show version` from `tests/fixtures/`, chosen when `DEVICE_MODE=mock` ([why](../../../docs/codespaces.md)).

## Break it

- `docker/podman stop bos-rtr-01` (or `containerlab` stop that node) and start the workflow. Watch **Pending Activities** in the UI: attempt count, last failure, next retry.
- Start the node again before attempt 5. The workflow finishes with no code change.
- Let it exceed 5 attempts. Read how the failure is reported in the workflow result.

## Done when

- [ ] Facts come back for all 4 devices (one workflow each).
- [ ] You can explain the difference between the activity failing and the workflow failing.
