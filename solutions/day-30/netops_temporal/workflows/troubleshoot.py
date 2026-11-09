"""Days 26-27: run the troubleshooting agent as a workflow, and (Day 27) act on its proposal
only once a human approves it.

The agent loop (the model picks a tool, the tool runs, the model reads the output, repeat)
runs here, in the workflow. The plugin makes each model call an activity, and the tools are
activities too, so a worker crash halfway resumes the investigation instead of restarting it.

Day 27: the agent proposes, deterministic code disposes. The agent's tools can't change
anything; a proposal waits for a `decide` update from someone other than the requester, and
only then goes to the compliance team's remediation (Day 23), Day 17's saga.

Day 28: a proposal with anything but policy lines trips the agent's output guardrail, and
never reaches a human.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import VersioningBehavior
from temporalio.exceptions import NexusOperationError

with workflow.unsafe.imports_passed_through():
    # The Agents SDK too: the plugin allows it into the sandbox on its own workers, but every
    # worker that lists this workflow (and the replay tests) must be able to import it.
    from agents import OutputGuardrailTripwireTriggered, Runner

    from netops_temporal.agents.troubleshooter import Investigation, troubleshooter
    from netops_temporal.constants import COMPLIANCE_ENDPOINT
    from netops_temporal.guardrails import MODE_COMMANDS
    from netops_temporal.models import (
        ChangeProposal,
        Decision,
        RemediationRequest,
        TroubleshootReport,
        TroubleshootRequest,
    )
    from netops_temporal.nexus.service import ComplianceService
    from netops_temporal.versioning import behavior


def config_lines(proposal: ChangeProposal) -> ChangeProposal:
    lines = [line for line in proposal.lines if line.strip().lower() not in MODE_COMMANDS]
    return proposal.model_copy(update={"lines": lines})


# Day 30: can wait a long time for a person, so it moves to each new build, rather than keeping
# an old one running until someone answers (and changes to it need patching).
@workflow.defn(versioning_behavior=behavior(VersioningBehavior.AUTO_UPGRADE))
class TroubleshootWorkflow:
    def __init__(self) -> None:
        self._stage = "investigating"
        self._proposal: ChangeProposal | None = None
        self._decision: Decision | None = None
        self._requested_by = ""

    @workflow.run
    async def run(self, req: TroubleshootRequest) -> TroubleshootReport:
        self._requested_by = req.requested_by
        try:
            result = await Runner.run(
                troubleshooter(),
                input=f"Device: {req.device}\nSymptom: {req.symptom}",
                context=Investigation(device=req.device),
                max_turns=12,  # a bound on the loop, so a confused model can't run forever
            )
        except OutputGuardrailTripwireTriggered as err:
            # Day 28: no approval to wait for. The proposal broke the rules, so nobody is
            # asked to approve it.
            self._stage = "done"
            rejected = err.guardrail_result.output.output_info
            return TroubleshootReport(
                device=req.device,
                findings=str(err.guardrail_result.agent_output),
                outcome="proposal blocked by guardrail, not policy lines: " + "; ".join(rejected),
            )
        # The run works on its own copy of the context: read the proposal from the result.
        investigation: Investigation = result.context_wrapper.context
        if investigation.proposal:
            self._proposal = config_lines(investigation.proposal)
        report = TroubleshootReport(
            device=req.device,
            findings=str(result.final_output),
            proposed_change=self._proposal,
        )
        if not self._proposal or not self._proposal.lines:
            self._stage = "done"
            return report

        # Day 27: wait for a human, but not forever (Day 11's pattern). The timer is on the
        # server, so it fires even if no worker is running when the time is up.
        self._stage = "awaiting_approval"
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=timedelta(minutes=req.approval_timeout_minutes),
            )
        except TimeoutError:
            self._stage = "done"
            report.outcome = "approval timed out: nothing changed"
            return report
        decision = self._decision
        if not decision.approve:
            self._stage = "done"
            report.outcome = f"rejected by {decision.approver}: nothing changed"
            return report

        self._stage = "applying"
        report.outcome, report.remediation = await self.apply(self._proposal, decision)
        self._stage = "done"
        return report

    async def apply(self, proposal: ChangeProposal, decision: Decision):
        """The approved lines go to the compliance team's remediate operation (Day 23): the
        same saga, lock and rules as every other config change. Not to the agent."""
        compliance = workflow.create_nexus_client(
            service=ComplianceService, endpoint=COMPLIANCE_ENDPOINT
        )
        try:
            result = await compliance.execute_operation(
                ComplianceService.remediate,
                RemediationRequest(
                    device=proposal.device,
                    missing_lines=proposal.lines,
                    dry_run=False,
                    # The approval is the change record (Day 24's REQUIRE_TICKET accepts it).
                    change_ticket=f"approved by {decision.approver}",
                ),
            )
        except NexusOperationError as err:
            reason = err.cause.message if err.cause else err.message
            return f"approved by {decision.approver}, but not applied: {reason}", None
        if result.ok:
            outcome = f"pushed {len(result.pushed_lines)} line(s)"
        else:
            undone = "rolled back" if result.rolled_back else "nothing changed"
            outcome = f"failed ({undone}): {result.error}"
        return f"approved by {decision.approver}: {outcome}", result

    # An update, not a signal: the caller learns at once whether the decision was accepted,
    # and the validator turns bad ones away before they're written into the history.
    @workflow.update
    def decide(self, decision: Decision) -> str:
        self._decision = decision
        self._stage = "decided"
        return "approved" if decision.approve else "rejected"

    @decide.validator
    def check_decision(self, decision: Decision) -> None:
        if self._stage != "awaiting_approval":
            raise ValueError(f"not awaiting approval (stage: {self._stage})")
        if not decision.approver:
            raise ValueError("a decision needs an approver")
        if decision.approver == self._requested_by:
            raise ValueError("you can't approve your own request")

    @workflow.query
    def proposal(self) -> ChangeProposal | None:
        return self._proposal

    @workflow.query
    def stage(self) -> str:
        return self._stage
