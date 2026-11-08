"""Test doubles shared by several test modules."""

import json
import random

import httpx2

from agentic_ticket_workflow.helpdesk import FakeHelpdesk
from agentic_ticket_workflow.models import ActionResult, ActRequest
from agentic_ticket_workflow.openai_llm import OpenAIChatModel


class ScriptedRandom(random.Random):
    """Returns the given values from random(), in order; raises StopIteration once they run out."""

    def __init__(self, values: list[float]):
        super().__init__()
        self.values = iter(values)

    def random(self) -> float:
        return next(self.values)


class _WriteCountingDict(dict):
    def __init__(self) -> None:
        super().__init__()
        self.writes = 0

    def __setitem__(self, key, value) -> None:
        self.writes += 1
        super().__setitem__(key, value)


class CountingHelpdesk(FakeHelpdesk):
    """Counts every call, and every action carried out: each write to `performed` is one execution.

    Counting writes, not keys, means a second execution under the same key, which would only overwrite the
    dict entry, still shows up."""

    def __init__(self, failure_rate: float, rng: random.Random | None = None) -> None:
        super().__init__(failure_rate, rng)
        self.performed = _WriteCountingDict()
        self.calls = 0

    @property
    def executions(self) -> int:
        return self.performed.writes

    def perform(self, req: ActRequest) -> ActionResult:
        self.calls += 1
        return super().perform(req)


def completion(content: str | None = None, tool_calls: list[dict] | None = None) -> dict:
    """A Chat Completions response body with one assistant message, as OpenAI sends it (extras included)."""
    message = {"role": "assistant", "content": content, "tool_calls": tool_calls, "refusal": None, "annotations": []}
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "model": "m",
        "choices": [{"index": 0, "message": message}],
    }


def tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class StubProvider:
    """An OpenAI-compatible endpoint behind the real SDK, with no network: each request gets the next reply.

    A reply is a 200 JSON body (dict), a raw 200 body (bytes), a `(status, body)` error response, or an
    exception the transport raises. The last reply repeats, so a retried attempt gets the same answer.
    `requests` holds every request body the SDK sent.
    """

    def __init__(self, *replies: dict | bytes | tuple[int, dict] | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[dict] = []
        client = httpx2.Client(transport=httpx2.MockTransport(self._handle))
        self.model = OpenAIChatModel("http://provider.test/v1", "test-model", "test-key", http_client=client)

    @property
    def calls(self) -> int:
        return len(self.requests)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        reply = self.replies[min(len(self.requests), len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, bytes):
            return httpx2.Response(200, content=reply, headers={"content-type": "application/json"})
        if isinstance(reply, tuple):
            return httpx2.Response(reply[0], json=reply[1])
        return httpx2.Response(200, json=reply)
