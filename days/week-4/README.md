# Week 4 — Nexus and AI

**Goal:** by Friday the compliance team owns remediation in its own namespace, and your
orchestrator calls it through a contract instead of starting their workflows. On top of that, a
model explains drift in plain words, and a troubleshooting agent investigates a device and
proposes a fix. A person approves every change, and the same deterministic saga applies it, so
the model never touches a device.

The week builds on Week 3's orchestrator:

1. **Split along team lines** (Days 22–24): the orchestrator stays in `default`, and remediation
   moves to the `compliance` namespace (pretend another team runs it). The endpoint
   `compliance-endpoint` connects the two. The caller depends only on a **service contract**: no
   workflow names, task queues or code from the other side.
2. **Add AI where it helps** (Days 25–28): an LLM call as an activity, an agent loop whose model
   calls and tool calls are activities, a human approval step, and tools and guardrails you can
   test.

| Day | Topic | Temporal features |
| --- | --- | --- |
| [22](day-22-nexus-sync/README.md) | First Nexus service: the compliance team's policy | Nexus services, endpoints, `sync_operation`, a second namespace |
| [23](day-23-nexus-async/README.md) | Remediation as an async Nexus operation | `workflow_run_operation`, cancellation across namespaces, `workflow.wait` |
| [24](day-24-nexus-contracts/README.md) | Changing a service without breaking its callers | compatible contract changes, `HandlerError` vs `OperationError` |
| [25](day-25-llm-activity/README.md) | An LLM call as an activity: explaining drift | non-retryable vs retryable model errors, structured output, `patched` |
| [26](day-26-durable-agent/README.md) | A durable troubleshooting agent | `OpenAIAgentsPlugin`, `activity_as_tool`, model calls as activities |
| [27](day-27-human-in-the-loop/README.md) | Human in the loop: the agent proposes, you decide | updates with validators, `wait_condition` with a timeout, Nexus from an agent workflow |
| [28](day-28-mcp-guardrails/README.md) | MCP tools and guardrails | `temporal_mcp_server`, MCP tool activities, output guardrails |

## What you need

- **Nexus (Days 22–24):** the `compliance` namespace, which `lab/start-temporal.sh` creates, and
  the endpoint, which `lab/nexus-endpoint.sh` creates on Day 22. From Day 23 you run two
  workers: the main one and the compliance team's (`netops_temporal.workers.compliance`).
- **A language model (Days 25–28):** any server that speaks the OpenAI chat-completions API, set
  with `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` in `.env`. The default is
  [Ollama](https://ollama.com) on your laptop with `qwen2.5:7b`: free, offline, and your device
  output never leaves your machine. [Lab setup](../../docs/lab-setup.md) shows how to install it.
  A hosted provider (OpenAI, Azure OpenAI, a gateway your company runs) works the same way.
  In mock mode (`LLM_MODE=mock`, or just `LAB_MODE=mock`) a scripted model stands in, so
  every test and exercise runs without one.
- **The cEOS lab** is optional all week. With `LAB_MODE=live`, an approved change on Day 27 or 28
  **is pushed to your cEOS device**, through Day 17's saga.

After pulling Week 4, run `uv sync`: Day 25 adds `openai`, Day 26 adds
`temporalio[openai-agents]`, and Day 28 adds `temporalio-openai-agents[mcp]`.

**A change from the original outline:** it used GitHub Models through Copilot as the model
provider. GitHub retired GitHub Models in July 2026, so the course talks to any
OpenAI-compatible server instead. Copilot still appears on Day 28, as one of the editors that
can use the course's MCP server.

**End-of-week checkpoint:** you can explain why remediation is called through an endpoint and
not as a child workflow, which parts of an agent run are activities and why, what stops the agent
from changing a device by itself, and what happens to an investigation when the worker dies
halfway.

Docs: [Nexus overview](https://docs.temporal.io/nexus) ·
[Python Nexus feature guide](https://docs.temporal.io/develop/python/nexus/feature-guide) ·
[Python AI integrations](https://docs.temporal.io/develop/python/integrations) ·
[AI cookbook](https://docs.temporal.io/ai/cookbook/)
