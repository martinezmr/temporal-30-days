# Day 23 — Async Nexus operations backed by workflows

[← Day 22](../day-22-nexus-sync/README.md) · [Day 24 →](../day-24-nexus-contracts/README.md)

## Goal

The orchestrator triggers remediation through Nexus, and remediation runs as a full workflow in the `compliance` namespace.

## Build

1. Add to the contract: `remediate: nexusrpc.Operation[RemediationRequest, RemediationResult]`.
2. Handler, using a workflow-run operation:

    ```python
    @nexus.workflow_run_operation
    async def remediate(self, ctx: nexus.WorkflowRunOperationContext,
                        req: RemediationRequest) -> nexus.WorkflowHandle[RemediationResult]:
        return await ctx.start_workflow(
            ConfigComplianceWorkflow.run, req, id=f"compliance-{req.device}")
    ```

3. Move `ConfigComplianceWorkflow` and its activities to the compliance worker.
4. Orchestrator: replace the direct child with

    ```python
    handle = await nexus.start_operation(ComplianceService.remediate, req)
    # ...later
    result = await handle
    ```

## Learn

- `start_operation` returns a handle you can await later or `cancel()`.
- Cancellation types: `WAIT_COMPLETED` (default), `WAIT_REQUESTED`, `TRY_CANCEL`, `ABANDON`.
- Pending cancellations aren't delivered after the caller workflow completes — wait for operations to settle first.

## Break it

- Stop the compliance worker mid-remediation. The orchestrator just waits. Restart; it completes.
- Cancel the caller and watch the cancellation reach `ConfigComplianceWorkflow` (and its saga run).

## Done when

- [ ] A drift detected in `default` produces a `ConfigComplianceWorkflow` in `compliance`, linked both ways in the UI.
