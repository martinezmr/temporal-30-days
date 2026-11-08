"""Days 22-23: the compliance team's implementation of ComplianceService.

It runs on the compliance team's worker (workers/compliance.py), in their namespace. They can
change how a policy is decided (a database, an approval flow) without any caller changing code,
as long as the contract in service.py stays the same.
"""

import nexusrpc
from nexusrpc.handler import StartOperationContext, service_handler, sync_operation
from temporalio import nexus
from temporalio.common import SearchAttributePair, TypedSearchAttributes
from temporalio.exceptions import WorkflowAlreadyStartedError

from netops_temporal.constants import COMPLIANCE_TASK_QUEUE
from netops_temporal.models import Policy, PolicyRequest, RemediationRequest, RemediationResult
from netops_temporal.nexus.service import ComplianceService
from netops_temporal.observability import DEVICE_SA
from netops_temporal.policies import POLICIES
from netops_temporal.workflows.remediation import ConfigRemediationWorkflow


@service_handler(service=ComplianceService)
class ComplianceServiceHandler:
    # A sync operation answers straight away, inside the Nexus request (a few seconds at most).
    @sync_operation
    async def get_policy(self, ctx: StartOperationContext, req: PolicyRequest) -> Policy:
        if req.role not in POLICIES:
            # The caller sent something wrong: fail now, don't retry.
            raise nexusrpc.HandlerError(
                f"no policy for role {req.role!r}", type=nexusrpc.HandlerErrorType.BAD_REQUEST
            )
        return Policy(role=req.role, required_lines=POLICIES[req.role])

    # Day 23: a workflow-backed operation. The handler only *starts* the workflow and returns
    # its handle; the caller waits for the workflow's result, however long it takes.
    @nexus.workflow_run_operation
    async def remediate(
        self, ctx: nexus.WorkflowRunOperationContext, req: RemediationRequest
    ) -> nexus.WorkflowHandle[RemediationResult]:
        try:
            return await ctx.start_workflow(
                ConfigRemediationWorkflow.run,
                req,
                # Day 16's lock, now kept by the team that owns remediation.
                id=f"remediate-config-{req.device}",
                task_queue=COMPLIANCE_TASK_QUEUE,
                # Day 20: findable by device, and readable at a glance, in their namespace.
                search_attributes=TypedSearchAttributes(
                    [SearchAttributePair(DEVICE_SA, req.device)]
                ),
                static_summary=(
                    f"config remediation for {req.device}" + (" (dry run)" if req.dry_run else "")
                ),
                static_details="Missing lines:\n"
                + "\n".join(f"- `{line}`" for line in req.missing_lines),
            )
        except WorkflowAlreadyStartedError as err:
            # Not worth retrying: fail the operation, with a message the caller can show.
            raise nexusrpc.OperationError(
                f"remediate-config-{req.device} already running",
                state=nexusrpc.OperationErrorState.FAILED,
            ) from err
