"""Day 26: run the troubleshooting agent as a workflow.

The agent loop (the model picks a tool, the tool runs, the model reads the output, repeat)
runs here, in the workflow. The plugin makes each model call an activity, and the tools are
activities too, so a worker crash halfway resumes the investigation instead of restarting it.
"""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    # The Agents SDK too: the plugin allows it into the sandbox on its own workers, but every
    # worker that lists this workflow (and the replay tests) must be able to import it.
    from agents import Runner

    from netops_temporal.agents.troubleshooter import Investigation, troubleshooter
    from netops_temporal.models import TroubleshootReport, TroubleshootRequest


@workflow.defn
class TroubleshootWorkflow:
    @workflow.run
    async def run(self, req: TroubleshootRequest) -> TroubleshootReport:
        result = await Runner.run(
            troubleshooter(),
            input=f"Device: {req.device}\nSymptom: {req.symptom}",
            context=Investigation(device=req.device),
            max_turns=12,  # a bound on the loop, so a confused model can't run forever
        )
        # The run works on its own copy of the context: read the proposal from the result.
        investigation: Investigation = result.context_wrapper.context
        return TroubleshootReport(
            device=req.device,
            findings=str(result.final_output),
            proposed_change=investigation.proposal,
        )
