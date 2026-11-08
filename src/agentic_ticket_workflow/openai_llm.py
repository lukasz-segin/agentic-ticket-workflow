"""Real model over any OpenAI-compatible Chat Completions endpoint (FR-009): OpenAI, Azure OpenAI v1, Ollama, ...

The only module that imports an LLM SDK. It returns the same message shape as `FakeChatModel`, so the
real model goes through the same tool loop (`agent.decide`) and the same rule checks. Provider errors
become the `agent` exceptions with fixed messages (`from None`): SDK errors and response bodies may
quote the request, i.e. ticket text.
"""

from typing import TYPE_CHECKING, Any

import openai
from pydantic import BaseModel, Field, ValidationError

from agentic_ticket_workflow import agent

if TYPE_CHECKING:
    import httpx2

# Per provider call. A `decide` attempt makes up to `max_steps` (6) calls inside its 60 s activity timeout.
CALL_TIMEOUT_SECONDS = 20.0
# Statuses a retry may fix: the ones the SDK itself would retry. Temporal's DECIDE_RETRY does the retrying.
_RETRYABLE_STATUSES = frozenset({408, 409, 429})


class _Message(BaseModel):
    content: str | None = None
    # Each call is checked by `agent.decide` before anything runs; here it only has to be an object.
    tool_calls: list[dict[str, Any]] | None = None


class _Choice(BaseModel):
    message: _Message


class _Completion(BaseModel):
    choices: list[_Choice] = Field(min_length=1)


class OpenAIChatModel:
    def __init__(self, base_url: str, model: str, api_key: str, *, http_client: httpx2.Client | None = None) -> None:
        self.model = model
        self.client = openai.OpenAI(
            base_url=base_url,
            # The SDK refuses a missing key and would fall back to OPENAI_API_KEY; keyless servers ignore it.
            api_key=api_key or "unused",
            max_retries=0,
            timeout=CALL_TIMEOUT_SECONDS,
            http_client=http_client,
        )

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            # Raw response: the body is validated below, not by the SDK's lenient model construction.
            raw = self.client.chat.completions.with_raw_response.create(
                model=self.model,
                messages=messages,
                tools=tools,
                response_format={"type": "json_object"},
            )
        except openai.APIConnectionError as exc:  # includes APITimeoutError
            raise agent.ModelUnavailable("provider unreachable", error_type=type(exc).__name__) from None
        except openai.APIStatusError as exc:
            error = agent.ModelUnavailable if _retryable(exc.status_code) else agent.ModelRequestRejected
            raise error(f"provider returned {exc.status_code}", error_type=type(exc).__name__) from None
        try:
            message = _Completion.model_validate_json(raw.text).choices[0].message
        except ValidationError as exc:  # also covers a body that isn't JSON
            raise agent.UnreadableModelAnswer(f"response does not parse: {exc.error_count()} error(s)") from None
        # Only these keys go back into the conversation: stricter servers reject the extras the SDK adds.
        return {"role": "assistant", "content": message.content, "tool_calls": message.tool_calls or None}


def _retryable(status: int) -> bool:
    return status in _RETRYABLE_STATUSES or status >= 500
