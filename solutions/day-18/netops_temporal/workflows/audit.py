"""Day 18: ComplianceAuditWorkflow. Check every device once, return a report, finish.

The orchestrator is a long-running loop with state, so it waits with timers. This audit has no
state between runs: each night stands alone. That's what a Schedule is for (tools/schedules.py).
"""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from netops_temporal.models import AuditReport, AuditRequest
    from netops_temporal.workflows.compliance_cycle import collect_compliance


@workflow.defn
class ComplianceAuditWorkflow:
    @workflow.run
    async def run(self, req: AuditRequest) -> AuditReport:
        started_at = workflow.now()
        # The same check the orchestrator runs each cycle. It only reports: no remediation.
        states = await collect_compliance(req.devices)
        workflow.logger.info("audit: %s", {d: s.status for d, s in sorted(states.items())})
        return AuditReport(started_at=started_at, states=states)
