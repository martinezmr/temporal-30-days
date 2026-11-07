# Day 06 — Testing

[← Day 05](../day-05-heartbeats-and-threads/README.md) · [Day 07 →](../day-07-parallel-backup/README.md)

## Goal

Fast tests with no lab, plus a replay test that will become your CI gate.

## Learn

- `WorkflowEnvironment.start_time_skipping()` — an in-process test server where timers jump forward.
- Mock activities by registering a function with the same name: `@activity.defn(name="get_device_facts")`.
- `ActivityEnvironment` — unit-test an activity alone (heartbeats, cancellation).
- `Replayer` — replays a saved history against current code and fails on non-determinism.
- Docs: [Testing](https://docs.temporal.io/develop/python/best-practices/testing-suite)

## Build

1. Mocked activity test:

    ```python
    @activity.defn(name="get_device_facts")
    async def fake_facts(device: str) -> DeviceFacts:
        return DeviceFacts(device=device, model="cEOSLab", version="4.32.0F")

    async def test_get_facts():
        async with await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter) as env:
            async with Worker(env.client, task_queue="t", workflows=[GetFactsWorkflow],
                              activities=[fake_facts]):
                r = await env.client.execute_workflow(GetFactsWorkflow.run, "bos-rtr-01",
                                                      id="t1", task_queue="t")
        assert r.version == "4.32.0F"
    ```

2. Replay test:

    ```bash
    temporal workflow show --workflow-id facts-bos-rtr-01 -o json > tests/histories/get_facts.json
    ```

    ```python
    async def test_replay_get_facts():
        history = WorkflowHistory.from_json("facts", Path("tests/histories/get_facts.json").read_text())
        await Replayer(workflows=[GetFactsWorkflow],
                       data_converter=pydantic_data_converter).replay_workflow(history)
    ```

3. An `ActivityEnvironment` test for `collect_show_tech` that asserts it heartbeats.

## Break it

Reorder activities in `GetFactsWorkflow` and run the replay test. It fails — good. That failure in CI is what saves running workflows on Day 30.

## Done when

- [ ] `uv run pytest` runs in seconds with the lab off.
- [ ] At least one history lives in `tests/histories/`.
