# Day 28 — AI pattern 4: MCP tools and guardrails

[← Day 27](../day-27-human-in-the-loop/README.md) · [Capstone →](../../capstone/day-29-assemble-orchestrator/README.md)

## Goal

Reusable network tools over MCP, and guardrails you can prove with tests.

## Build

1. Wrap your read-only lookups (`show` commands, Nautobot device queries) as an MCP server (e.g. with the `mcp` Python package's FastMCP).
2. Register it with the plugin and use it from the agent:

    ```python
    OpenAIAgentsPlugin(mcp_servers=[...named server factory...])
    # in the workflow
    agent = Agent(..., mcp_servers=[temporal_mcp_server("netops-tools")])
    ```

    (`uv add "temporalio-openai-agents[mcp]"`; see the integration page for the factory signature.)
3. The same MCP server now works from Claude Desktop or any MCP client too.

## Guardrails to implement

- [ ] **Command allowlist** in the tool activity: only `show ...` commands; anything else raises non-retryable.
- [ ] **Max turns** on the agent run.
- [ ] **Cost cap**: count tokens per workflow in state; stop when over budget.
- [ ] **Replay test** of a saved agent history (Day 6) — agent workflows must replay too.
- [ ] **Audit**: the approval, the real diff and the model's reasoning all live in history.

## Checkpoint

Explain which parts of the AI flow are deterministic (the workflow) and which aren't (model calls, in activities), and why that split is what makes it safe to point an agent at a network.
