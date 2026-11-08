# Day 25 — An LLM call is an activity

[← Day 24](../day-24-nexus-contracts/README.md) · [Day 26 →](../day-26-durable-agent/README.md)

**Time:** 75 minutes · **Needs the cEOS lab?** No (`LAB_MODE=mock`) · **Solution:** [`solutions/day-25/`](../../../solutions/day-25/)

## Why today matters

`status` tells the on-call engineer *what* drifted: `config: 2 missing`. It doesn't tell them
whether to care at 3 a.m. Today a language model reads each drift and writes a short explanation
of what's different, how risky it is, and the likely cause, and the orchestrator keeps it with
the device's state.

There's nothing magic about the model call. To Temporal it's an HTTP request to an API that's
slow, sometimes rate-limited, sometimes down, sometimes answers in the wrong format, and costs
money every time you call it. You've handled APIs like that since Day 3: put the call in an
activity and let Temporal deal with the failures.

Network analogy: a TAC case. You send the symptoms, wait, and get an analysis back. Sometimes the
queue is full and you try again later. You don't open a second case for the same problem just
because you lost the browser tab: the first answer is still on file.

## Concept

### Same rules as any flaky API

| Problem | What handles it |
| --- | --- |
| Slow (seconds to tens of seconds) | An activity with a `start_to_close_timeout` (60 s) |
| Rate limits (429), outages (5xx), no connection | Retries (`maximum_attempts=4`) |
| An answer that isn't valid JSON, or doesn't fit the schema | Also a retry. Models get it right on the next attempt most of the time |
| A wrong API key (401/403), an unknown model (400/404) | `ApplicationError(non_retryable=True)`: retrying won't help |
| Paying for every call | The answer is in the workflow's history: a replay reuses it |

The last row is the durability payoff. When a worker restarts, the orchestrator is rebuilt by
replaying its history, and the recorded explanation is used. The model isn't called again. The
orchestrator also keeps an explanation while a device's drift stays the same, so a drift that
lasts all week is explained once, not 672 times.

### Structured output, validated

The prompt asks for JSON matching a schema, and the request sets
`response_format={"type": "json_object"}`. The answer is then parsed with
`DriftExplanation.model_validate_json`:

```python
class DriftExplanation(BaseModel):
    summary: str
    risk: Literal["low", "medium", "high"]
    likely_cause: str
```

If it doesn't validate (prose, missing fields, `"risk": "extreme"`), the attempt fails and is
retried. A half-parsed answer is never passed on.

### Which model?

Any server that speaks the **OpenAI chat-completions API**, which is nearly all of them: Ollama on
your laptop, OpenAI, Microsoft Foundry, vLLM, or your company's AI gateway. Three settings choose
it:

| Setting | Default | For a hosted provider |
| --- | --- | --- |
| `LLM_BASE_URL` | `http://localhost:11434/v1` (Ollama) | The provider's OpenAI-compatible URL |
| `LLM_API_KEY` | empty (Ollama doesn't check it) | Your key |
| `LLM_MODEL` | `qwen2.5:7b` | The model or deployment name |
| `LLM_MODE` | same as `LAB_MODE` | `live` for a real model with mock devices |

The course runs a local model with **Ollama**: free, no account, and nothing leaves your laptop,
which matters when the prompt contains device config. With `LAB_MODE=mock` (and in every test)
you don't need a model at all: `llm/mock.py` gives canned answers.

(The course first planned to use GitHub Models, the API behind the Copilot models. GitHub retired
it on 2026-07-30. The code doesn't care: swapping providers is changing three settings.)

## Walkthrough

### 1. `llm/client.py`: one call, four kinds of failure

```python
# file: netops_temporal/llm/client.py
def complete_structured[T: BaseModel](system: str, user: str, schema: type[T]) -> T:
    """Ask the model, and return its answer parsed as `schema`, or raise an LLMError."""
    if llm_mode() == "mock":
        text = mock.reply(user)
    else:
        text = ask(system, user)
    try:
        return schema.model_validate_json(text)
    except ValidationError as err:
        # Never pass on half an answer: fail this attempt instead.
        raise LLMMalformedOutput(f"answer doesn't fit {schema.__name__}: {text[:200]!r}") from err
```

`ask` makes the request with `openai.OpenAI(base_url=..., api_key=..., max_retries=0)`.
`max_retries=0` turns off the library's own retries: Temporal does the retrying, and the history
shows every attempt. `ask` turns the library's errors into four of ours: `LLMAuthError`
(401/403), `LLMBadRequest` (400/404), `LLMUnavailable` (429, 5xx, no connection) and, from the
parsing above, `LLMMalformedOutput`.

Mock mode replaces only the HTTP request. The canned answer is JSON text, so parsing and
validation still run.

### 2. `activities/explain.py`: deciding what's worth retrying

```python
# file: netops_temporal/activities/explain.py
@activity.defn
def explain_drift(req: ExplainRequest) -> DriftExplanation:
    system = SYSTEM.format(schema=json.dumps(DriftExplanation.model_json_schema()))
    user = json.dumps({"device": req.device, "drift": [d.model_dump() for d in req.drift]})
    try:
        return complete_structured(system, user, DriftExplanation)
    except LLMAuthError as err:
        # A bad token won't fix itself: fail now instead of using up every attempt.
        raise ApplicationError(str(err), type="LLMAuth", non_retryable=True) from err
    except LLMBadRequest as err:
        raise ApplicationError(str(err), type="LLMBadRequest", non_retryable=True) from err
```

`LLMUnavailable` and `LLMMalformedOutput` go out as they are: ordinary exceptions, which
Temporal retries. Like the device activities, it runs on the `device-io` workers (Day 21).

### 3. `workflows/orchestrator.py`: explain each new drift

```python
# file: netops_temporal/workflows/orchestrator.py
            results = list((await collect_compliance(inp.devices)).values())
            # Day 25: a language model explains each drift. Calling it is a new command, so
            # orchestrators that started before this change skip it (Day 19).
            if workflow.patched("explain-drift"):
                await gather_all(*(self.explain(s) for s in results if s.status == "drifted"))
```

```python
async def explain(self, state: ComplianceState) -> None:
    previous = self.state.get(state.device)
    if previous and previous.explanation and previous.drift == state.drift:
        # The same drift as last cycle: keep the answer instead of paying for it again.
        state.explanation = previous.explanation
        return
    try:
        state.explanation = await workflow.execute_activity(
            explain_drift,
            ExplainRequest(device=state.device, drift=state.drift),
            task_queue=DEVICE_IO_TASK_QUEUE,
            start_to_close_timeout=timedelta(seconds=60),
            # Rate limits and malformed answers get three more tries; a bad token none.
            retry_policy=RetryPolicy(maximum_attempts=4),
        )
    except ActivityError as err:
        # No explanation is a shame, not a reason to stop checking devices.
        workflow.logger.warning("no explanation for %s: %s", state.device, err.cause)
```

`ComplianceState` has a new `explanation` field, and `status` prints it under the device.

### 4. The tests

`tests/test_explain.py`:

- `test_explain_drift_mock`: the canned answers, `medium` risk for config drift and `high` for a
  version drift.
- `test_auth_error_non_retryable` and `test_rate_limit_is_retryable`: a fake OpenAI client raises
  a 401 (non-retryable `LLMAuth`) or a 429 (a plain, retryable exception).
- `test_malformed_llm_json_is_retryable`: prose, an off-schema `risk`, and missing fields all fail
  the attempt with `LLMMalformedOutput`.
- `test_malformed_mock_output_succeeds_on_retry`: `MOCK_LLM_MALFORMED=1`, through a real worker.
  The history shows the activity succeeded on attempt 2.
- `test_explanation_reused_after_worker_restart`: one cycle, stop the workers, start new ones.
  The new worker rebuilds the orchestrator from history and has the same explanation, a second
  cycle keeps it, and the model was called exactly once.

The Day 16 fan-out tests and the continue-as-new test now run on a real dev server: with the
extra activities, the time-skipping server sometimes left a Nexus operation hanging.

## Run it

Run `uv sync` first: today adds the `openai` package.

In mock mode it just works: start the workers and the orchestrator as usual, and `status` shows
an explanation under each drifted device:

```
  bos-acc-01  drifted   config: 1 missing (want 1 policy line(s) present)
                        [medium risk] bos-acc-01 is missing 1 line(s) the compliance policy requires. ...
                        -> config: dry run, would add 1 line(s)
```

For a real model, install [Ollama](https://ollama.com) (`brew install ollama` on a Mac), then:

```bash
ollama serve              # leave it running, or start the Ollama app
ollama pull qwen2.5:7b    # about 4.7 GB, once
```

The defaults in `.env.example` point at it. A real model is used whenever `LAB_MODE=live`. To
keep the devices mocked and use the real model, restart the main worker with `LAB_MODE=mock
LLM_MODE=live`. Terminate the orchestrator and upgrade, and start again. The first cycle takes longer now: a local model needs a
few seconds per device. In the UI, each `explain_drift` activity shows the model's answer as its
result.

To use a hosted provider instead, set all three in `.env`, for example:

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4.1-mini
```

## Break it

1. **Ask for a model that doesn't exist.** `LLM_MODEL=no-such-model`, restart the main worker, and start a new orchestrator. The server answers 404, the activity fails with
   `LLMBadRequest`, non-retryable, on attempt 1. `status` shows no explanation, and remediations
   still happen. (A wrong `LLM_API_KEY` against a hosted provider does the same with `LLMAuth`.)
2. **Stop the model server.** Quit Ollama and `force-check` with a device whose drift changed (or
   a new orchestrator). The activity fails with `LLMUnavailable`. In the UI's pending
   activities, watch the attempt count climb, with the last failure
   `the LLM provider is unavailable: Connection error.`. After the fourth attempt the cycle
   finishes without an explanation.
   Restart Ollama and the next cycle explains it.
3. **Restart the worker right after the explanation.** Once `status` shows explanations, stop the
   main worker and start it again, then `status`. The explanations are the same, and the history
   has one `explain_drift` per device. The new worker rebuilt the orchestrator from history,
   without calling the model. `test_explanation_reused_after_worker_restart` checks exactly this.
4. **Get a malformed answer.** In mock mode, restart the main worker with
   `MOCK_LLM_MALFORMED=1`: every first attempt gets prose instead of JSON. Each `explain_drift`
   fails once with `LLMMalformedOutput` and succeeds on attempt 2, and in the history its
   **ActivityTaskStarted** event shows `attempt: 2`.

## Check yourself

1. Why is the LLM call an activity, not code in the workflow?
2. Which LLM failures are retried, and which aren't? Why?
3. Why does the client set `max_retries=0`?
4. A worker restarts. Is the model called again for the explanations it already gave? Why not?
5. What happens to an explanation that's off-schema?

<details>
<summary>Answers</summary>

1. It's I/O with an unpredictable answer: a workflow must be deterministic (Day 2). As an
   activity, it gets timeouts and retries, and its result is recorded.
2. Retried: rate limits, outages, connection errors, and malformed answers: they may well work
   next time. Not retried: a bad key or an invalid request (unknown model): they never will.
3. So Temporal is the only thing retrying, with a policy you chose, and every attempt is visible
   in the history.
4. No. The result is in the history, and replay uses it. The orchestrator also keeps an
   explanation while the drift doesn't change, so new cycles don't pay again either.
5. Validation fails, the attempt raises `LLMMalformedOutput`, and Temporal retries it. It's never
   stored half-parsed.

</details>

## Solution

[`solutions/day-25/`](../../../solutions/day-25/): new `llm/client.py`, `llm/mock.py` and
`activities/explain.py`; `DriftExplanation`, `ExplainRequest` and `ComplianceState.explanation`
in `models.py`; the patched `explain` step in `workflows/orchestrator.py`; `explain_drift` in
`workers/main.py`; the explanation in `starters/orchestrator.py`'s `status`. Outside the solution:
the `openai` dependency, and the `LLM_*` settings in `.env.example`. Tests:
`tests/test_explain.py`.
