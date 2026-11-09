"""Day 22: the compliance team's implementation of ComplianceService.

It runs on the compliance team's worker (workers/compliance.py), in their namespace. They can
change how a policy is decided (a database, an approval flow) without any caller changing code,
as long as the contract in service.py stays the same.
"""

import nexusrpc
from nexusrpc.handler import StartOperationContext, service_handler, sync_operation

from netops_temporal.models import Policy, PolicyRequest
from netops_temporal.nexus.service import ComplianceService
from netops_temporal.policies import POLICIES


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
