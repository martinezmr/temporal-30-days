# Day 17 — Saga: safe config push with rollback

[← Day 16](../day-16-fan-out/README.md) · [Day 18 →](../day-18-schedules/README.md)

## Goal

`ConfigComplianceWorkflow` changes a device and puts it back exactly as it was if anything fails.

## Learn

- **Saga:** each step that changes the world registers its undo; on failure, run the undos in reverse.
- Cleanup after cancellation: catch `asyncio.CancelledError` in the workflow, run the compensating activity, then re-raise.
- Arista config sessions give you a staged change, a real diff, and `commit timer` (auto-rollback unless confirmed) — a saga built into the device.

## Build

Activities (eAPI):

| Activity | eAPI commands |
| --- | --- |
| `stage_config(device, session, lines)` | `configure session <s>`, the lines, `end` |
| `get_session_diff(device, session)` | `show session-config named <s> diffs` |
| `commit_with_timer(device, session, minutes)` | `configure session <s>`, `commit timer 00:05:00` |
| `verify_state(device, intent)` | re-pull running config, re-diff against intent |
| `confirm_commit(device, session)` | `configure session <s>`, `commit` |
| `abort_session(device, session)` | `configure session <s>`, `abort` |

Workflow:

```python
compensations: list[Callable[[], Awaitable]] = []
try:
    await act(stage_config, ...);      compensations.append(lambda: act(abort_session, ...))
    diff = await act(get_session_diff, ...)   # stored in history = audit trail
    await act(commit_with_timer, ...)  # device rolls back by itself if we never confirm
    ok = await act(verify_state, ...)
    if not ok:
        raise ApplicationError("verification failed", non_retryable=True)
    await act(confirm_commit, ...)
except BaseException:
    for undo in reversed(compensations):
        await undo()
    raise
```

Check the exact session commands against your cEOS version — run them by hand first.

## Break it

- Make `verify_state` return `False`. The device must end up with its original config.
- Kill the worker after `commit_with_timer`. The device's own timer rolls back even if Temporal never returns — two layers of safety.

## Done when

- [ ] A diff from Nautobot intent lands on the device, is verified, and confirmed.
- [ ] A failed verification leaves no trace on the device.
