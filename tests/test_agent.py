import json

import pytest

from agentic_ticket_workflow.agent import DisallowedValue, UnknownCustomer, UnreadableModelAnswer, decide
from agentic_ticket_workflow.fake_llm import FakeChatModel
from agentic_ticket_workflow.models import Ticket


class AlwaysToolModel:
    def complete(self, messages, tools):
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "search_kb", "arguments": json.dumps({"query": "password"})},
                }
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


@pytest.mark.parametrize(
    ("ticket_id", "category", "priority", "action_type", "reason"),
    [
        ("T-3", "technical", "urgent", "escalate", "possible_outage"),
        ("T-4", "account", "high", "reply", None),
        ("T-5", "other", "low", "close", "not_support_request"),
    ],
)
def test_example_tickets_get_their_expected_decision(tickets, ticket_id, category, priority, action_type, reason):
    result = decide(tickets[ticket_id], FakeChatModel())
    action = result.decision.action
    assert (result.decision.category, result.decision.priority, action.type) == (category, priority, action_type)
    if reason is not None:
        assert action.reason == reason


def test_t4_cites_kb4_after_checking_customer_and_invoices(tickets):
    # KB-3 and KB-4 tie on the ticket text alone; the customer's "suspended" status breaks the tie.
    result = decide(tickets["T-4"], FakeChatModel())
    assert result.decision.action.article_ids == ["KB-4"]
    assert [call.name for call in result.tool_calls] == ["get_customer", "get_invoices", "search_kb"]


def test_unmatched_ticket_escalates_with_no_matching_rule():
    ticket = Ticket(ticket_id="X-1", customer_id="C-200", subject="Question", body="What colour is the sky?")
    result = decide(ticket, FakeChatModel())
    assert result.decision.action.type == "escalate"
    assert result.decision.action.reason == "no_matching_rule"


@pytest.mark.parametrize("ticket_id", ["T-2", "T-6"])
def test_refund_tickets_match_no_rule_yet(tickets, ticket_id):
    # The first matching rule wins: an S-03 keyword here would shadow S-04's refund rules.
    result = decide(tickets[ticket_id], FakeChatModel())
    assert result.decision.action.type == "escalate"
    assert result.decision.action.reason == "no_matching_rule"


class MustNotBeCalledModel:
    def complete(self, messages, tools):
        pytest.fail("the model was consulted for an unknown customer")


def test_unknown_customer_is_detected_before_the_model(tickets):
    with pytest.raises(UnknownCustomer) as caught:
        decide(tickets["T-7"], MustNotBeCalledModel())
    assert "C-999" not in str(caught.value)


def test_step_limit_raises_unreadable(tickets):
    with pytest.raises(UnreadableModelAnswer):
        decide(tickets["T-1"], AlwaysToolModel(), max_steps=3)


def test_unparseable_decision_raises_unreadable(tickets):
    with pytest.raises(UnreadableModelAnswer):
        decide(tickets["T-1"], NotJsonModel())


class AnswerModel:
    def __init__(self, answer):
        self.answer = answer

    def complete(self, messages, tools):
        return {"role": "assistant", "content": json.dumps(self.answer), "tool_calls": None}


def test_disallowed_category_raises_with_the_rule_code_only(tickets):
    answer = {"category": "SECRET MODEL TEXT", "priority": "normal", "action": {"type": "close", "reason": "x"}}
    with pytest.raises(DisallowedValue) as caught:
        decide(tickets["T-1"], AnswerModel(answer))
    assert caught.value.code == "category_not_allowed"
    assert caught.value.__cause__ is None
    assert "SECRET" not in str(caught.value)


def test_missing_action_is_still_unreadable(tickets):
    with pytest.raises(UnreadableModelAnswer):
        decide(tickets["T-1"], AnswerModel({"category": "account", "priority": "normal"}))


class BadToolCallModel:
    def __init__(self, call):
        self.call = call

    def complete(self, messages, tools):
        return {"role": "assistant", "content": None, "tool_calls": [self.call]}


@pytest.mark.parametrize(
    "call",
    [
        {"id": "c1", "type": "function", "function": {"name": "search_kb", "arguments": '{"query": 123}'}},
        {"type": "function", "function": {"name": "search_kb", "arguments": '{"query": "password"}'}},
        {"id": "c1", "type": "function"},
        {"id": "c1", "type": "function", "function": {"name": "SECRET TICKET TEXT", "arguments": "{}"}},
    ],
    ids=["non-string-argument", "missing-id", "missing-function", "unknown-tool"],
)
def test_bad_tool_call_raises_unreadable_without_echoing_model_text(tickets, call):
    with pytest.raises(UnreadableModelAnswer) as caught:
        decide(tickets["T-1"], BadToolCallModel(call))
    assert caught.value.__cause__ is None
    assert "SECRET" not in str(caught.value)
