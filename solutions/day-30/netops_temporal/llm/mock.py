"""Day 25: canned model answers for LAB_MODE=mock, so the course runs without a token.

The answer depends on what drifted, and comes back as JSON text, so the real parsing and
validation in client.py still run.

    MOCK_LLM_MALFORMED=1   the first attempt gets prose instead of JSON, like a model that
                           forgot the format; the retry gets a proper answer
"""

import json
import os

from temporalio import activity


def reply(user: str) -> str:
    request = json.loads(user)
    if os.environ.get("MOCK_LLM_MALFORMED") == "1" and first_attempt():
        return "Sure! The device is missing some config. Let me know if you need more help."
    device = request["device"]
    kinds = {d["kind"] for d in request["drift"]}
    if "version" in kinds:
        answer = {
            "summary": f"{device} runs a different EOS version from its intent.",
            "risk": "high",
            "likely_cause": "An upgrade that was skipped or rolled back.",
        }
    else:
        missing = sum(len(d["missing_lines"]) for d in request["drift"])
        answer = {
            "summary": f"{device} is missing {missing} line(s) the compliance policy requires.",
            "risk": "medium",
            "likely_cause": "A manual change, or a device built before the policy line existed.",
        }
    return json.dumps(answer)


def first_attempt() -> bool:
    return not activity.in_activity() or activity.info().attempt == 1
