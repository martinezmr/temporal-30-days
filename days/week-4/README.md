# Week 4 — Nexus and AI

**Goal:** split the system along team lines with Nexus, then add AI where it helps (explaining drift, troubleshooting, proposing fixes) while keeping a human and a deterministic workflow in charge of every change.

**Nexus in one paragraph.** Nexus lets a workflow in one namespace call an operation owned by another namespace through a named **endpoint**, without knowing the other side's workflow names, task queues or code. The caller depends only on a **service contract**. Python Nexus is GA (Replay 2026); the newer `@nexus.temporal_operation` handler style is still experimental, so this week uses the stable `sync_operation` / `workflow_run_operation` decorators.

**The split you'll build:** the orchestrator stays in `default`. Remediation moves to `compliance` (pretend another team owns it). An endpoint `compliance-endpoint` connects them. `lab/start-temporal.sh` already created the `compliance` namespace.

| Day | Topic |
| --- | --- |
| [22](day-22-nexus-sync/README.md) | First Nexus service (sync operation) |
| [23](day-23-nexus-async/README.md) | Async Nexus operations backed by workflows |
| [24](day-24-nexus-contracts/README.md) | Nexus errors, timeouts and contracts |
| [25](day-25-llm-activity/README.md) | AI 1: LLM call as an activity |
| [26](day-26-durable-agent/README.md) | AI 2: a durable agent with device tools |
| [27](day-27-human-in-the-loop/README.md) | AI 3: human in the loop |
| [28](day-28-mcp-guardrails/README.md) | AI 4: MCP tools and guardrails |

Docs: [Nexus overview](https://docs.temporal.io/nexus) · [Python Nexus quickstart](https://docs.temporal.io/develop/python/nexus/quickstart) · [Python Nexus feature guide](https://docs.temporal.io/develop/python/nexus/feature-guide) · [Python AI integrations](https://docs.temporal.io/develop/python/integrations) · [AI cookbook](https://docs.temporal.io/ai/cookbook/)
