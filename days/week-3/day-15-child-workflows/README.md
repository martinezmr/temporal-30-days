# Day 15 — Child workflows and parent close policy

[← Week 2](../../week-2/README.md) · [Day 16 →](../day-16-fan-out/README.md)

## Goal

The orchestrator starts a remediation workflow per drifted device.

## Learn

- `workflow.execute_child_workflow(...)` — start and wait for the result.
- `workflow.start_child_workflow(...)` — get a handle, keep looping, await it later.
- Children have their own history (good: the orchestrator's stays small) and their own ID.
- `ParentClosePolicy`: `TERMINATE` (default), `REQUEST_CANCEL`, `ABANDON` — what happens to the child when the parent run ends, **including on continue-as-new**.
- Docs: [Child workflows](https://docs.temporal.io/develop/python/workflows/child-workflows)

## Build

1. Stubs: `ConfigComplianceWorkflow(ComplianceInput)` and `DeviceUpgradeWorkflow(UpgradeInput)` that log and sleep 30 s.
2. In the orchestrator, after computing drift:

    ```python
    for report in drifted:
        if report.version_drift:
            await workflow.start_child_workflow(
                DeviceUpgradeWorkflow.run, UpgradeInput(device=report.device, ...),
                id=f"upgrade-{report.device}",
                parent_close_policy=ParentClosePolicy.ABANDON,
            )
        elif report.config_diff:
            await workflow.start_child_workflow(
                ConfigComplianceWorkflow.run, ComplianceInput(device=report.device, diff=report.config_diff),
                id=f"compliance-{report.device}",
                parent_close_policy=ParentClosePolicy.ABANDON,
            )
    ```

## Why ABANDON

The orchestrator continues-as-new regularly. With the default `TERMINATE`, every continue-as-new would kill a half-finished upgrade. Never do that to a router.

## Break it

Force a continue-as-new while a child is running (set the loop count low). With `TERMINATE` the child dies; with `ABANDON` it finishes.

## Done when

- [ ] Drift on a device produces a visible child in the UI, linked from the parent's history.
