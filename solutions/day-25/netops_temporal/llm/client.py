"""Day 25: one structured LLM call, to any OpenAI-compatible API.

Most model servers speak the OpenAI chat-completions API: Ollama on your laptop, OpenAI,
Microsoft Foundry, vLLM, or your company's AI gateway. So the standard `openai` package talks
to all of them, and three settings choose which:

    LLM_BASE_URL   default http://localhost:11434/v1 (Ollama)
    LLM_API_KEY    the provider's key (Ollama doesn't need one)
    LLM_MODEL      default qwen2.5:7b
    LLM_MODE       "live" or "mock"; defaults to LAB_MODE, so mock devices can still use a
                   real model with LLM_MODE=live

Every failure comes out as one of four exceptions, so the activity can decide what's worth
retrying without knowing anything about HTTP.
"""

import os

import openai
from pydantic import BaseModel, ValidationError

from netops_temporal.constants import lab_mode
from netops_temporal.llm import mock

DEFAULT_BASE_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible API
DEFAULT_MODEL = "qwen2.5:7b"


class LLMError(Exception):
    """Something went wrong calling the model."""


class LLMAuthError(LLMError):
    """401/403: the API key is missing or wrong. Retrying won't help."""


class LLMBadRequest(LLMError):
    """400/404: the request itself is wrong (say, an unknown model). Retrying won't help."""


class LLMUnavailable(LLMError):
    """429 or 5xx, or no connection: rate-limited or down. Worth trying again later."""


class LLMMalformedOutput(LLMError):
    """The model answered, but not with JSON that fits the schema. Models do that sometimes;
    a second attempt usually works."""


def llm_mode() -> str:
    return os.environ.get("LLM_MODE") or lab_mode()


def model() -> str:
    return os.environ.get("LLM_MODEL", DEFAULT_MODEL)


def openai_client() -> openai.OpenAI:
    return openai.OpenAI(
        base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
        # The client insists on a key; local servers like Ollama ignore it.
        api_key=os.environ.get("LLM_API_KEY") or "not-needed",
        # Temporal retries the activity, with a policy you can see in the history.
        max_retries=0,
    )


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


def ask(system: str, user: str) -> str:
    try:
        response = openai_client().chat.completions.create(
            model=model(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},  # JSON only, no chat around it
            timeout=50,  # inside the activity's 60-second start-to-close timeout
        )
    except (openai.AuthenticationError, openai.PermissionDeniedError) as err:
        raise LLMAuthError(f"the LLM provider refused the API key: {err}") from err
    except (openai.BadRequestError, openai.NotFoundError) as err:
        raise LLMBadRequest(f"the LLM provider rejected the request: {err}") from err
    except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError) as err:
        # `from None`: a connection error drags a long chain of exceptions behind it, too big
        # for Temporal to keep as the pending activity's last failure. The message is enough.
        raise LLMUnavailable(f"the LLM provider is unavailable: {err}") from None
    return response.choices[0].message.content or ""
