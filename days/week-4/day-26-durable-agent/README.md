# Day 26 — AI pattern 2: a durable agent with device tools

[← Day 25](../day-25-llm-activity/README.md) · [Day 27 →](../day-27-human-in-the-loop/README.md)

## Goal

An agent that troubleshoots your lab using read-only device tools, where every model call and tool call is durable.

## Learn

- The agent loop (model decides → tool runs → repeat) maps cleanly onto Temporal: the loop is the workflow; each model call and tool call is an activity.
- Temporal's **OpenAI Agents SDK integration** does this wiring for you. Experimental plugins exist for Google ADK, Strands, LangGraph, Deep Agents and others.
- Docs: [OpenAI Agents integration](https://docs.temporal.io/develop/python/integrations/openai-agents) · [All integrations](https://docs.temporal.io/develop/python/integrations)

## Build

```bash
uv add temporalio-openai-agents
```

```python
# client and worker
client = await Client.connect(TEMPORAL_ADDRESS, plugins=[
    OpenAIAgentsPlugin(model_params=ModelActivityParameters(start_to_close_timeout=timedelta(seconds=60)))
])

# workflow
@workflow.defn
class TroubleshootingAgentWorkflow:
    @workflow.run
    async def run(self, question: str) -> str:
        agent = Agent(
            name="NetOps troubleshooter",
            instructions="You diagnose Arista EOS issues. Use tools; never guess device state.",
            tools=[
                activity_as_tool(get_interfaces, start_to_close_timeout=timedelta(seconds=30)),
                activity_as_tool(get_bgp_summary, start_to_close_timeout=timedelta(seconds=30)),
                activity_as_tool(get_lldp_neighbors, start_to_close_timeout=timedelta(seconds=30)),
                activity_as_tool(get_logging, start_to_close_timeout=timedelta(seconds=30)),
            ],
        )
        result = await Runner.run(agent, question)
        return result.final_output
```

Register the tool activities on the worker as usual. Check the integration page for the exact import paths on your installed version.

**Not on OpenAI?** The Agents SDK can use other providers through its model-provider options; or skip the framework and hand-write the loop as a workflow calling an `llm_step` activity and tool activities — a good exercise either way.

## Exercise

`shutdown` `Ethernet1` on `bos-acc-01`, then ask: *"Why can't bos-acc-01 reach nyc-rtr-01?"* Read the history: every tool call is an event.

## Rule

Tools in this workflow are **read-only**. Changes go through Day 27.

## Done when

- [ ] The agent finds the shut interface, and killing the worker mid-investigation resumes where it left off.
