"""Day 15: fix one device's config drift. A child workflow of the orchestrator.

Today it only plans: it returns the diff it would push. Day 17 makes it push for real, safely.
"""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from netops_temporal.models import RemediationRequest, RemediationResult


@workflow.defn
class ConfigRemediationWorkflow:
    @workflow.run
    async def run(self, req: RemediationRequest) -> RemediationResult:
        diff = "\n".join(f"+{line}" for line in req.missing_lines)
        workflow.logger.info("%s: would add %d line(s)", req.device, len(req.missing_lines))
        return RemediationResult(device=req.device, ok=True, diff=diff)
