"""Keyword-rule fake model (FR-009): no network, no key, same message shape as a real model.

It calls the tools in a fixed order, then picks the first rule whose keyword occurs in the
ticket text. Later slices only append rules to RULES.
"""

import json
from dataclasses import dataclass
from typing import Any, Literal

from agentic_ticket_workflow.models import Category, Decision, Priority


@dataclass(frozen=True)
class Rule:
    keywords: tuple[str, ...]
    category: Category
    priority: Priority
    action: Literal["reply", "escalate", "close"]
    needs_invoices: bool = False
    reason: str = "matched_rule"  # used by escalate / close rules


RULES: tuple[Rule, ...] = (Rule(("password", "log in", "login"), "account", "normal", "reply"),)


def _match(text: str) -> Rule | None:
    text = text.lower()
    return next((rule for rule in RULES if any(keyword in text for keyword in rule.keywords)), None)


def _tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
        ],
    }


def _tool_results(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Map each tool already called (by name, from assistant tool_calls) to its result."""
    names_by_id = {
        call["id"]: call["function"]["name"]
        for message in messages
        if message["role"] == "assistant"
        for call in message.get("tool_calls") or []
    }
    return {
        names_by_id[message["tool_call_id"]]: json.loads(message["content"])
        for message in messages
        if message["role"] == "tool" and message["tool_call_id"] in names_by_id
    }


class FakeChatModel:
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        ticket = json.loads(next(m["content"] for m in messages if m["role"] == "user"))
        text = f"{ticket['subject']} {ticket['body']}"
        rule = _match(text)
        results = _tool_results(messages)

        if "get_customer" not in results:
            return _tool_call("get_customer", {"customer_id": ticket["customer_id"]})
        if rule and rule.needs_invoices and "get_invoices" not in results:
            return _tool_call("get_invoices", {"customer_id": ticket["customer_id"]})
        if "search_kb" not in results:
            return _tool_call("search_kb", {"query": text})

        decision = self._decision(rule, results["search_kb"])
        return {"role": "assistant", "content": decision.model_dump_json(), "tool_calls": None}

    @staticmethod
    def _decision(rule: Rule | None, kb_hits: list[dict[str, Any]]) -> Decision:
        if rule is None:
            return Decision.model_validate(
                {
                    "category": "other",
                    "priority": "normal",
                    "action": {"type": "escalate", "reason": "no_matching_rule"},
                }
            )
        if rule.action == "reply":
            if not kb_hits:
                action = {"type": "escalate", "reason": "no_kb_article"}
            else:
                top = kb_hits[0]
                action = {
                    "type": "reply",
                    "message": f"{top['title']}: {top['text']}",
                    "article_ids": [top["article_id"]],
                }
        else:
            action = {"type": rule.action, "reason": rule.reason}
        return Decision.model_validate({"category": rule.category, "priority": rule.priority, "action": action})
