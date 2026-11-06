import json

import pytest

from agentic_ticket_workflow.agent import UnreadableModelAnswer, decide
from agentic_ticket_workflow.fake_llm import FakeChatModel


class AlwaysToolModel:
    def complete(self, messages, tools):
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "search_kb", "arguments": json.dumps({"query": "password"})}}
            ],
        }


class NotJsonModel:
    def complete(self, messages, tools):
        return {"role": "assistant", "content": "not json", "tool_calls": None}


class RecordingModel(FakeChatModel):
    def __init__(self):
        self.seen: list[list[dict]] = []

    def complete(self, messages, tools):
        self.seen.append(list(messages))
        return super().complete(messages, tools)


def test_t1_is_answered_with_kb1(tickets):
    result = decide(tickets["T-1"], FakeChatModel())
    assert (result.decision.category, result.decision.priority) == ("account", "normal")
    assert result.decision.action.type == "reply"
    assert result.decision.action.article_ids == ["KB-1"]
    names = [call.name for call in result.tool_calls]
    assert "get_customer" in names and "search_kb" in names


def test_assistant_message_precedes_its_tool_results(tickets):
    model = RecordingModel()
    decide(tickets["T-1"], model)
    final = model.seen[-1]
    for i, message in enumerate(final):
        if message["role"] == "tool":
            ids = {c["id"] for m in final[:i] if m["role"] == "assistant" for c in m["tool_calls"]}
            assert message["tool_call_id"] in ids


def test_t5_escalates_with_no_matching_rule(tickets):
    result = decide(tickets["T-5"], FakeChatModel())
    assert result.decision.action.type == "escalate"
    assert result.decision.action.reason == "no_matching_rule"


def test_step_limit_raises_unreadable(tickets):
    with pytest.raises(UnreadableModelAnswer):
        decide(tickets["T-1"], AlwaysToolModel(), max_steps=3)


def test_unparseable_decision_raises_unreadable(tickets):
    with pytest.raises(UnreadableModelAnswer):
        decide(tickets["T-1"], NotJsonModel())
