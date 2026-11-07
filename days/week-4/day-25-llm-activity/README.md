# Day 25 — AI pattern 1: LLM call as an activity

[← Day 24](../day-24-nexus-contracts/README.md) · [Day 26 →](../day-26-durable-agent/README.md)

## Goal

Every drift report comes with a plain-English explanation and a risk level, produced durably.

## Learn

- An LLM call is a slow, flaky, expensive API call: it belongs in an activity with a timeout and a retry policy.
- 429 / 5xx → retryable. 400 (bad request, prompt too long) → non-retryable.
- Durability pays twice: if the worker dies after the model answered, the answer is already in history — you don't pay for, or get a *different* answer from, the same call again.

## Build

```python
class DriftExplanation(BaseModel):
    summary: str
    risk: Literal["low", "medium", "high"]
    likely_cause: str

@activity.defn
async def explain_drift(report: DriftReport) -> DriftExplanation:
    # Use the Anthropic or OpenAI SDK with structured output / tool-forced JSON,
    # then DriftExplanation.model_validate(...)
    ...
```

- `uv add anthropic` (or `openai`); key from `.env`.
- Call it with `start_to_close_timeout=60s`, `RetryPolicy(maximum_attempts=4, non_retryable_error_types=["BadRequest"])`.
- Put the summary on the child's `static_summary` / memo so it shows in the UI.

## Break it

- Kill the worker right after the activity completes. On restart, the explanation is reused, not regenerated.
- Point the key at an invalid value — non-retryable, fails fast.

## Done when

- [ ] Every `ConfigComplianceWorkflow` shows a human-readable "why" in the UI.
