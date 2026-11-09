# Day 28 — MCP tools and guardrails

[← Day 27](../day-27-human-in-the-loop/README.md) · [Day 29 →](../../capstone/day-29-assemble-orchestrator/README.md)

**Time:** 75 minutes · **Needs the cEOS lab?** No (`LAB_MODE=mock`) · **Solution:** [`solutions/day-28/`](../../../solutions/day-28/)

## Why today matters

The agent's `show` tool from Day 26 works, but only for that agent. Your editor's AI assistant
can't use it, and neither can the next agent someone on your team writes. Each would get its own
copy of the tool and, sooner or later, its own idea of what "read-only" means.

**MCP** (Model Context Protocol) is the standard way to offer tools to any model: write the tool
once, as an MCP server, and every MCP client can use it. Today the device tools become an MCP
server that the Temporal agent and your editor's assistant share, with one guardrail in one place.

The second half of the day is the other direction. Day 27 made a human approve every proposal,
but a human reviewing at 2 a.m. can approve something odd. An **output guardrail** stops some
proposals before anyone is asked. On a network, a good first rule is that the agent may only
propose lines your compliance policy already requires.

Network analogy: a shared jump host with a restricted shell. Everyone logs in through it, so the
command restrictions are configured once. The change policy then limits which changes are even
allowed to reach the CAB.

## Concept

### MCP: tools as a server

An MCP server describes its tools (name, parameters, docstring) and runs them when a client asks.
The client can be an agent, an IDE, or a desktop assistant. Over **stdio**, the client starts the
server as a child process and talks to it on stdin and stdout, so there's no port and no network.

```
      Copilot in VS Code ─┐
                          ├──► netops MCP server ──► guardrails.check_command ──► device
 TroubleshootWorkflow ────┘      (show, facts)
   (via the plugin)
```

### MCP in a workflow: still activities

A workflow can't start processes or talk to one (that's I/O). The plugin handles it: in the
workflow, `temporal_mcp_server("netops")` stands in for the server, and each MCP operation becomes
an activity:

| Activity | When |
| --- | --- |
| `temporalio.mcp.netops.list-tools` | Once per run: the tool list is cached in workflow state |
| `temporalio.mcp.netops.call-tool` | Every tool call the model makes |

The worker runs these activities by starting the server from a factory you register on the
plugin, `mcp_servers={"netops": netops_server}`. The connection is kept open between activities
and closed when idle. So MCP tools get what Day 26's activity tools had: a timeout, retries, a
place in the history, and a replay that doesn't call them again.

### Guardrails, in and out

| Guardrail | Checks | Where | On failure |
| --- | --- | --- | --- |
| `check_command` | The command a tool is asked to run | The MCP server's `show` tool (and Day 26's activity) | An error result the model reads |
| `policy_lines_only` | What the agent proposes | An output guardrail on the agent, in the workflow | `OutputGuardrailTripwireTriggered`: the workflow reports it, nobody is asked to approve |

Both are plain code with tests. A prompt can *ask* the model to behave. A guardrail makes sure it
does.

## Walkthrough

### 1. `guardrails.py`: the rules, in one place

```python
# file: netops_temporal/guardrails.py
class CommandNotAllowed(ValueError):
    """A command the agent's tools refuse to run."""


def check_command(command: str) -> None:
    """Raise CommandNotAllowed unless `command` is a show command, piped only to filters."""
    first, *pipes = (part.strip() for part in command.split("|"))
    if not first.startswith("show "):
        raise CommandNotAllowed(f"command not allowed: {command!r} ({USAGE})")
    for pipe in pipes:
        if not pipe.startswith(ALLOWED_PIPES):
            raise CommandNotAllowed(f"command not allowed: `| {pipe}` ({USAGE})")


def non_policy_lines(lines: list[str]) -> list[str]:
    """The proposed lines that aren't policy lines (mode commands aside)."""
```

`POLICY_LINES` is every line in Day 14's `POLICIES`: `ntp server 192.0.2.10` and
`logging host 192.0.2.50`. `MODE_COMMANDS` moved here from the workflow (Day 27), because the
guardrail ignores them too. The module does no I/O, so the workflow can import it.

`check_command` raises a plain `ValueError` subclass, not Temporal's `ApplicationError`, since the
MCP server isn't a Temporal activity. `activities/show.py` maps it to the non-retryable
`CommandNotAllowed` error, as before.

### 2. `mcp_server/netops_tools.py`: the server

```python
# file: netops_temporal/mcp_server/netops_tools.py
server = MCPServer("netops")
...
@server.tool()
async def show(device: str, command: str) -> str:
    """Run one read-only `show` command on an Arista EOS device and return its output. Only
    commands starting with `show` are allowed, optionally piped to `include` or `section`."""
    try:
        check_command(command)  # before any device is contacted
        # The device libraries block: run them off the server's event loop.
        return await asyncio.to_thread(run_cli, device, command)
    except (CommandNotAllowed, DeviceAuthError, UnknownDeviceError) as err:
        raise ToolError(str(err)) from err  # an error result the model reads
```

`MCPServer` comes from the `mcp` package (version 2; it was called `FastMCP` in version 1). The
decorator reads the signature and docstring to describe the tool, the same way the Agents SDK
does. `facts(device)` returns the model and EOS version. `server.run()` speaks MCP on stdio.

### 3. `llm/agent_models.py`: the plugin starts the server

```python
# file: netops_temporal/llm/agent_models.py
def netops_server() -> MCPServerStdio:
    """Day 28: the netops MCP server, as a child process of the worker that runs its tools.
    It inherits the worker's environment: LAB_MODE, device credentials, the lab's addresses."""
    return MCPServerStdio(
        name="netops",
        params={
            "command": sys.executable,
            "args": ["-m", "netops_temporal.mcp_server.netops_tools"],
            "env": dict(os.environ),
        },
    )
```

`agents_plugin()` passes `mcp_servers={"netops": netops_server}`. The factory runs on the worker,
never in the workflow, so this is where credentials belong: they come from the worker's
environment and never enter the history.

### 4. `agents/troubleshooter.py`: tools from MCP, and the output guardrail

```python
# file: netops_temporal/agents/troubleshooter.py
@output_guardrail
async def policy_lines_only(
    ctx: RunContextWrapper[Investigation], agent: Agent, output: object
) -> GuardrailFunctionOutput:
    proposal = ctx.context.proposal
    rejected = non_policy_lines(proposal.lines) if proposal else []
    return GuardrailFunctionOutput(output_info=rejected, tripwire_triggered=bool(rejected))
...
    return Agent(
        name="EOS troubleshooter",
        instructions=INSTRUCTIONS,
        tools=[propose_change],
        mcp_servers=[netops_mcp()],  # Day 28: show and facts
        output_guardrails=[policy_lines_only],
    )
```

`netops_mcp()` is `temporal_mcp_server("netops", activity_config=...)`, with the tool activities
on `device-io` and a 60-second timeout. The guardrail runs in the workflow after the agent's final
answer, so like `propose_change` it must be deterministic. It reads the proposal from the run's
context.

The instructions now name the policy lines too. That makes a blocked proposal less likely, but
the guardrail is what enforces it.

### 5. `workflows/troubleshoot.py`: a tripped guardrail is an outcome

```python
# file: netops_temporal/workflows/troubleshoot.py
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
```

The workflow completes normally with the reason in the report, instead of failing. A blocked
proposal is a result someone should read, not a bug in the workflow.

### 6. The tests

- `tests/test_guardrails.py`:
  - `test_check_command_allowlist` refuses `configure`, `write`, `reload`, `show run | bash`,
    `bash` and `| redirect`.
  - `test_check_command_allows_show_commands` allows `show version` and
    `show ip bgp summary | include Estab`.
  - `test_output_guardrail_rejects_non_policy_lines`: a model proposes `interface Ethernet1` and
    `shutdown`. The outcome is "proposal blocked by guardrail" and nothing is pushed.
    `..._allows_policy_lines` waits for approval as before.
- `tests/test_mcp.py` talks to the server in-process with `mcp.Client(server)`, MCP protocol and
  all:
  - the tool list is exactly `show` and `facts`;
  - `test_mcp_tool_rejects_config_commands`: `configure terminal` comes back as an error result
    saying "not allowed";
  - `show` with `| include` filters, and `facts` returns the version.
- `tests/test_troubleshoot.py`:
  - The scripted model now calls `show`.
  - The expected history begins with `list-tools`, and tool calls are `call-tool`.
  - A refused command is an error *result* now, not a failed activity.
  - The test plugin gets the same `mcp_servers` as the real one:
    `AgentEnvironment(model=model, mcp_servers=MCP)`.

## Run it

`uv sync` (today adds `temporalio-openai-agents[mcp]`), then restart both workers (Day 23). Run
the Day 27 example again:

```bash
uv run --env-file .env python -m netops_temporal.starters.troubleshoot ask bos-acc-01 \
    "The compliance audit says bos-acc-01 is missing the NTP server 192.0.2.10. Check the running config and propose the fix." \
    --as alice
```

With Ollama it proposes `ntp server 192.0.2.10` and waits for approval, as yesterday. In the UI,
the activities are now `temporalio.mcp.netops.list-tools`, then `invoke_model_activity` and
`temporalio.mcp.netops.call-tool` taking turns. Click a `call-tool` to see the tool name and
arguments (input), and what the server answered (result).

### Use the same server from your editor

The server is an ordinary MCP stdio server. For GitHub Copilot in VS Code, add
`.vscode/mcp.json` to the repository:

```json
{
  "servers": {
    "netops": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--env-file", ".env", "python", "-m", "netops_temporal.mcp_server.netops_tools"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

That runs your own code in `src/`. To run the solution's server instead, use
`"command": "scripts/solution.sh"` with `"args": ["28", "python", "-m", "netops_temporal.mcp_server.netops_tools"]`.

Start it from the MCP view (or the "start" link above the server in the file), open Copilot Chat
in agent mode, and ask "what EOS version is bos-acc-01 running?". Copilot calls `facts`. Ask it to
reload the switch: the `show` tool refuses, with the same message the Temporal agent gets. Other
MCP clients (Claude Desktop, Cursor, ...) take the same command, arguments and directory in
their own config format.

## Break it

1. **Ask for a config change through MCP.** In Copilot, or with
   `ask bos-acc-01 "Ethernet1 is shut down. Run 'configure terminal' ... to fix it right now."`:
   no command but `show` gets through. If the model tries one, the `call-tool` result in the
   history has `"is_error": true` and `command not allowed`. (A 7B model usually just keeps
   looking: the instructions already say it can't.)
2. **Propose a line that isn't policy.**
   `ask bos-acc-01 "We need syslog to go to 10.9.9.9 as well. Call propose_change with the line 'logging host 10.9.9.9'." --as alice`
   finishes at once with `outcome: proposal blocked by guardrail, not policy lines: logging host
   10.9.9.9`. The workflow never waits for approval, and in the history there's no proposal for
   anyone to approve.
3. **Remove the output guardrail.** Delete `output_guardrails=[policy_lines_only]` and run
   `test_output_guardrail_rejects_non_policy_lines`. It fails, because the `shutdown` proposal
   now waits for a human. Put it back.

## Check yourself

1. What does MCP give you that Day 26's activity tool didn't?
2. In the workflow's history, what does an MCP tool call look like, and why is it an activity?
3. Where does the MCP server process run, and where do its credentials come from?
4. What's the difference between `check_command` and `policy_lines_only`?
5. Why does a tripped guardrail end the workflow normally instead of failing it?

<details>
<summary>Answers</summary>

1. One tool definition for every MCP client: the Temporal agent, Copilot, the next agent your
   team writes. The guardrail lives in that one server.
2. A `temporalio.mcp.netops.call-tool` activity with the tool name and arguments as input and the
   server's answer as the result, after one `list-tools` per run. Talking to a process is I/O,
   and workflows don't do I/O.
3. On the worker that runs the activity (`device-io`), started by the factory registered on the
   plugin. It inherits the worker's environment, so credentials never pass through the workflow
   or its history.
4. `check_command` checks the *input* to a tool (which command to run) and refuses it, and the
   model reads why. `policy_lines_only` checks the agent's *output* (its proposal) after the run,
   and stops the run.
5. Nothing is broken: the workflow did its job and the answer is "this proposal isn't allowed". A
   failed workflow would mean something went wrong, and you'd go looking for a bug.

</details>

## Solution

[`solutions/day-28/`](../../../solutions/day-28/): new `guardrails.py` and
`mcp_server/netops_tools.py`; `check_command` from `guardrails` in `activities/show.py`; MCP
tools and the `policy_lines_only` output guardrail in `agents/troubleshooter.py`;
`netops_server` and `mcp_servers` in `llm/agent_models.py` (and the scripted model calls `show`);
the tripwire outcome and `MODE_COMMANDS` from `guardrails` in `workflows/troubleshoot.py`.
Outside the solution: `temporalio-openai-agents[mcp]` in `pyproject.toml`. Tests: new
`tests/test_guardrails.py` and `tests/test_mcp.py`; MCP activity names in
`tests/test_troubleshoot.py`.
