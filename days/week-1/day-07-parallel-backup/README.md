# Day 07 — Mini-project: parallel config backup + intent fetch

[← Day 06](../day-06-testing/README.md) · [Week 2 →](../../week-2/README.md)

## Goal

Your first real workflow: inventory from Nautobot, config from every device in parallel, and a report that survives partial failure.

## Build

1. `activities/nautobot.py`: `list_devices() -> list[str]` via Nautobot GraphQL (`/api/graphql/`, token from `.env`).
2. `activities/eapi.py`: `get_running_config(device) -> DeviceState` (`show running-config` with `"format": "text"`, plus version).
3. `workflows/backup.py`:

    ```python
    @workflow.defn
    class BackupConfigsWorkflow:
        @workflow.run
        async def run(self) -> BackupReport:
            devices = await workflow.execute_activity(list_devices, start_to_close_timeout=timedelta(seconds=30))
            results = await asyncio.gather(
                *[workflow.execute_activity(get_running_config, d,
                      start_to_close_timeout=timedelta(seconds=60),
                      retry_policy=RetryPolicy(maximum_attempts=3)) for d in devices],
                return_exceptions=True,
            )
            ok = [r for r in results if isinstance(r, DeviceState)]
            failed = [d for d, r in zip(devices, results) if isinstance(r, BaseException)]
            await workflow.execute_activity(save_backups, ok, start_to_close_timeout=timedelta(seconds=30))
            return BackupReport(saved=[s.device for s in ok], failed=failed)
    ```

4. `save_backups` writes to `backups/<device>.cfg` (gitignored) — idempotent by design.

## Stretch

`get_intended_config(device) -> DeviceIntent` that reads intent from Nautobot (config context, or Golden Config intended config). Week 2 diffs this against state.

## Break it

Stop one node. The report should list 3 saved, 1 failed, and the workflow should **succeed**.

## Done when

- [ ] You can explain every event in this workflow's history, including the parallel `ActivityTaskScheduled` events.
- [ ] Tests cover the partial-failure case with mocks.
- [ ] One line in `LEARNING.md` for each day this week.
