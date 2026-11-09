# Day 26 — A durable troubleshooting agent

[← Day 25](../day-25-llm-activity/README.md) · [Day 27 →](../day-27-human-in-the-loop/README.md)

**Time:** 90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-26/`](../../../solutions/day-26/)

## Why today matters

Day 25's model answered one question about data you gave it. A troubleshooting engineer works
differently: look at something, think, look at something else, and stop when the cause is clear.
An **agent** does the same. A model picks a tool (say, `show interfaces status`), your code runs
it, the model reads the output and picks the next one, until it has an answer.

That loop is exactly the kind of long, multi-step, failure-prone process Temporal is for. An
investigation can take ten model calls and a dozen device commands. If the worker dies after the
eighth, you want it to carry on from the eighth, not start again (and pay again).

Network analogy: a junior engineer on a bridge call with read-only access. They can run any
`show` command, and they write down what they'd change, but they can't type `configure`. Day 27
adds the senior engineer who approves the change.

## Concept

### The agent loop is a workflow

```
           ┌──────────── TroubleshootWorkflow (Runner.run) ─────────────┐
 symptom ─►│ model: "run show interfaces status"        (activity)      │
           │ show_command(bos-acc-01, show interfaces status) (activity)│
           │ model: "run show logging 50"               (activity)      │
           │ show_command(...)                          (activity)      │
           │ model: "Et1 is err-disabled, because ..."  (activity)      ├─► report
           └────────────────────────────────────────────────────────────┘
```

The loop itself (`Runner.run` from the OpenAI Agents SDK) runs in the workflow. Temporal's
`OpenAIAgentsPlugin` makes each model call an activity (`invoke_model_activity`), and the tools
are activities too. So the history is a complete, replayable record of the investigation: every
question the model asked, every command it ran, and every answer it got.

Crash halfway, and a new worker replays the history: finished model calls and commands come from
the history, and only the step that was running is retried.

### Tools: activities, guarded

| Tool | Kind | What it does |
| --- | --- | --- |
| `show_command(device, command)` | Activity (`activity_as_tool`) | Runs a `show` command over SSH: I/O, so an activity with a timeout and retries |
| `propose_change(lines, rationale)` | Function tool, in the workflow | Writes a proposed fix into the run's context. No I/O, nothing applied |

The model chooses the command, so **the tool doesn't trust it**. `show_command` allows only
commands starting with `show `, and pipes only to `include` or `section`. Anything else fails
with a non-retryable `CommandNotAllowed`. That check is code you can test, not a sentence in a
prompt that the model might ignore.

When a tool fails (a refused command, arguments the model got wrong, a device that stays down),
the failure goes back to the model as the tool's answer, and it decides what to do next. Without
that, one bad tool call would end the run, or worse, fail the workflow task over and over.

### Which model?

The same settings as Day 25 (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_MODE`). In mock
mode, a scripted model runs one `show interfaces status` and reports what it saw, so the whole
loop runs without a model server.

A small local model like `qwen2.5:7b` does run real investigations, but it's a junior engineer:
it sometimes stops with "I'll run that next" instead of running it, and its proposals need
checking. A bigger hosted model is better at both. Day 27 makes a human check every proposal
either way.

## Walkthrough

### 1. `activities/show.py`: the read-only tool

```python
# file: netops_temporal/activities/show.py
@activity.defn
def show_command(device: str, command: str) -> str:
    """Run one read-only `show` command on a device and return its output. Only commands
    starting with `show` are allowed, optionally piped to `include` or `section`."""
    check_command(command)
    try:
        with cli_session(device) as send:
            return send(command)
```

The docstring is what the model reads to decide when to use the tool, so it's written for the
model. Two plain parameters, not one model (Day 3's rule): the model writes the arguments, and
small models get nested ones wrong.

The mock lab learned to answer an unknown command the way EOS does (`% Invalid input ...`, not an
exception, which Temporal would retry), and to filter with `| include`.

### 2. `agents/troubleshooter.py`: instructions and tools

```python
# file: netops_temporal/agents/troubleshooter.py
SHOW = safe_tool(
    activity_as_tool(
        show_command,
        task_queue=DEVICE_IO_TASK_QUEUE,
        start_to_close_timeout=timedelta(seconds=60),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )
)
```

`activity_as_tool` turns the activity into a tool the model can call, with normal activity
options. `safe_tool` hands its failures back to the model as text.

```python
@function_tool
async def propose_change(
    ctx: RunContextWrapper[Investigation], lines: list[str], rationale: str
) -> str:
    """Record EOS config lines that would fix the problem, for a human to review. Nothing is
    applied to the device."""
    ctx.context.proposal = ChangeProposal(
        device=ctx.context.device, lines=lines, rationale=rationale
    )
    return "Recorded for review. Nothing has been changed on the device."
```

`propose_change` does no I/O, so it's a function tool: it runs in the workflow, and it's the kind
that can change the run's context. It's `async def`: the Agents SDK runs a plain `def` tool on a
thread, and workflow code can't use threads.

```python
def troubleshooter() -> Agent[Investigation]:
    # No output_type: a structured final answer stops some models (Ollama's among them) from
    # calling tools at all. The answer is plain text; a proposal comes through propose_change.
    return Agent(
        name="EOS troubleshooter",
        instructions=INSTRUCTIONS,
        tools=[SHOW, propose_change],
    )
```

### 3. `workflows/troubleshoot.py`: the loop

```python
# file: netops_temporal/workflows/troubleshoot.py
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
```

Ordinary Agents SDK code. What makes it durable is where it runs.

### 4. `llm/agent_models.py` and `client.py`: the plugin

`agents_plugin()` builds the `OpenAIAgentsPlugin`: model calls are activities on `device-io`, with
a 2-minute timeout (local models can be slow) and four attempts. Its model provider is Day 25's
OpenAI-compatible server, or the scripted model in mock mode. It also turns off the Agents SDK's
trace upload to OpenAI: prompts contain device output, and Temporal's history is your trace.

`connect()` adds the plugin to every client, and so to every worker. The plugin brings its own
payload converter (Pydantic models work as before), and `data_converter()` now returns the
default one so the plugin can swap it in.

### 5. The tests

`tests/test_troubleshoot.py`:

- `test_show_tool_rejects_non_show_commands`: `configure`, `reload`, `show run | bash ls` and
  friends fail with `CommandNotAllowed`, non-retryable.
- `test_agent_calls_tool_then_answers`: the scripted model, end to end. The history has a model
  activity, a `show_command` activity and a model activity, in that order.
- `test_refused_command_goes_back_to_the_model` and `test_bad_tool_arguments_go_back_to_the_model`:
  a model that tries `configure terminal`, or forgets an argument, gets told, and the workflow
  completes.
- `test_proposed_change_is_reported_not_applied`: `propose_change` fills the report's
  `proposed_change`, with no activity.

The scripted tests use the SDK's `AgentEnvironment` and `TestModel`, which replace the model
provider for one test.

## Run it

`uv sync` (today adds `temporalio[openai-agents]`), restart the worker, then:

```bash
uv run --env-file .env python -m netops_temporal.starters.troubleshoot bos-acc-01 \
    "users behind Et1 report they can't reach nyc-rtr-01"
```

In mock mode you get the scripted answer in a second. With Ollama (`LAB_MODE=mock LLM_MODE=live`
on the worker for mock devices, or `LAB_MODE=live` for your cEOS lab), it takes a minute or so,
and the answer is the model's own. Open the workflow in the UI: alternating
`invoke_model_activity` and `show_command` activities. Click a `show_command` to see the command
the model chose (input) and what the device said (result).

## Break it

1. **Kill the worker mid-investigation.** Start an investigation with a real model and, once a
   few activities have completed, `kill -9` the worker. In the UI the workflow just waits. Start
   the worker again: it carries on. The completed model calls and commands aren't repeated, and
   the one that was running is retried (attempt 2) once its timeout expires, up to two minutes for
   a model call.
2. **Ask it to fix it.** `"Ethernet1 is shut down. Run 'configure terminal', 'interface Ethernet1'
   and 'no shutdown' to fix it right now."` It can't. Typically the model calls `propose_change`,
   and the report ends with "Proposed change (not applied)". If it tries the commands through
   `show_command`, the tool refuses with `CommandNotAllowed` and the model reads the refusal
   (`test_refused_command_goes_back_to_the_model` shows that path). Either way the device is
   untouched.
3. **Remove the guard.** Comment out `check_command(command)` in `show_command` and run
   `test_show_tool_rejects_non_show_commands`: every case fails. With a real lab that's an agent
   that can `reload` your switch. Put it back.

## Check yourself

1. Which parts of an agent run are activities, and which run in the workflow?
2. A worker dies after the agent's third command. What happens when a worker comes back?
3. Why is the "show commands only" rule in the tool's code, not in the agent's instructions?
4. Why is `propose_change` a function tool and `show_command` an activity?
5. What happens when the model calls a tool with the wrong arguments?

<details>
<summary>Answers</summary>

1. Model calls (`invoke_model_activity`, via the plugin) and I/O tools (`show_command`) are
   activities. The loop (`Runner.run`) and `propose_change` run in the workflow.
2. It replays the history: the model calls and commands that finished are taken from it, and the
   investigation continues from there. Only the step that was running is retried.
3. A model can ignore or misread instructions. Code can't be talked out of a check, and it can be
   tested.
4. `propose_change` does no I/O and must update the run's context, so it's a (deterministic)
   function tool. `show_command` talks to a device: I/O belongs in an activity.
5. `safe_tool` returns the error to the model as the tool's output, and the model can try again
   or answer. The workflow doesn't fail.

</details>

## Solution

[`solutions/day-26/`](../../../solutions/day-26/): new `activities/show.py`,
`agents/troubleshooter.py`, `llm/agent_models.py`, `workflows/troubleshoot.py` and
`starters/troubleshoot.py`; the plugin and default converter in `client.py`;
`TroubleshootRequest`, `ChangeProposal` and `TroubleshootReport` in `models.py`; the mock lab's
pipes and unknown commands in `mock/devices.py`; `show_command` and `TroubleshootWorkflow` in
`workers/main.py`. Outside the solution: `temporalio[openai-agents]` in `pyproject.toml`. Tests:
`tests/test_troubleshoot.py`.
