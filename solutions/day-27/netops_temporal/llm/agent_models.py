"""Day 26: the models behind the troubleshooting agent, and the plugin that runs it on Temporal.

OpenAIAgentsPlugin turns every model call the agent makes into an activity. It asks a model
provider for the model to call: the same OpenAI-compatible server as Day 25 (LLM_BASE_URL,
LLM_API_KEY, LLM_MODEL), or, with LLM_MODE=mock, a scripted stand-in.
"""

import json
import re
from datetime import timedelta

from agents import Model, ModelProvider, OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI
from temporalio.common import RetryPolicy
from temporalio.contrib.openai_agents import ModelActivityParameters, OpenAIAgentsPlugin
from temporalio.contrib.openai_agents.testing import ResponseBuilders

from netops_temporal.constants import DEVICE_IO_TASK_QUEUE
from netops_temporal.llm import client as llm

# The Agents SDK uploads traces to OpenAI's platform by default. Prompts here include device
# output, which stays on your network: Temporal's history is the trace.
set_tracing_disabled(True)


class OpenAICompatibleProvider(ModelProvider):
    """Day 25's server, through the Agents SDK's chat-completions model."""

    def get_model(self, model_name: str | None) -> Model:
        return OpenAIChatCompletionsModel(
            model=model_name or llm.model(),
            openai_client=AsyncOpenAI(
                base_url=llm.base_url(),
                api_key=llm.api_key(),
                max_retries=0,  # Temporal retries the model activity
            ),
        )


class ScriptedTroubleshooter(Model):
    """LLM_MODE=mock: plays the model's part in a short investigation. The first turn asks
    for `show interfaces status`; the next one reads it and answers."""

    async def get_response(self, system_instructions, input, model_settings, tools,
                           output_schema, handoffs, tracing, **kwargs):  # fmt: skip
        items = [{"role": "user", "content": input}] if isinstance(input, str) else input
        outputs = [i["output"] for i in items if i.get("type") == "function_call_output"]
        if not outputs:
            question = next(i["content"] for i in items if i.get("role") == "user")
            device = re.search(r"Device: (\S+)", question).group(1)
            command = {"device": device, "command": "show interfaces status"}
            return ResponseBuilders.tool_call(json.dumps(command), "show_command")
        ports = [line for line in str(outputs[-1]).splitlines() if line.startswith("Et")]
        findings = "Interface status: " + "; ".join(" ".join(p.split()) for p in ports)
        return ResponseBuilders.output_message(findings)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError("the scripted model doesn't stream")


class ScriptedProvider(ModelProvider):
    def get_model(self, model_name: str | None) -> Model:
        return ScriptedTroubleshooter()


def agents_plugin() -> OpenAIAgentsPlugin:
    """Register on every client and worker (client.connect does it). Model calls are
    activities on the device-io workers, like the rest of the course's I/O (Day 21)."""
    return OpenAIAgentsPlugin(
        model_params=ModelActivityParameters(
            task_queue=DEVICE_IO_TASK_QUEUE,
            start_to_close_timeout=timedelta(seconds=120),  # a local model can be slow
            retry_policy=RetryPolicy(maximum_attempts=4),
        ),
        model_provider=ScriptedProvider()
        if llm.llm_mode() == "mock"
        else OpenAICompatibleProvider(),
    )
