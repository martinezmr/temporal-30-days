"""Day 25: ask a language model to explain a device's drift, for the on-call engineer.

An LLM call is a slow, flaky, paid-for API call: exactly what activities are for. Temporal
retries it when that can help, and records the answer, so a replay never pays for it again.
"""

import json

from temporalio import activity
from temporalio.exceptions import ApplicationError

from netops_temporal.llm.client import LLMAuthError, LLMBadRequest, complete_structured
from netops_temporal.models import DriftExplanation, ExplainRequest

SYSTEM = """You are a senior network engineer. Explain configuration drift on Arista EOS
devices to the on-call engineer: what's different, how risky it is, and the most likely cause.
Be brief and concrete. Reply with a JSON object only, matching this JSON schema:
{schema}"""


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
    # LLMUnavailable and LLMMalformedOutput are left as they are: ordinary exceptions, which
    # Temporal retries under the workflow's retry policy.
