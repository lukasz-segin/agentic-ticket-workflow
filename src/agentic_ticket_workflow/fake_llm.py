"""Keyword-rule fake model (FR-009): no network, no key, same message shape as a real model.

It calls the tools in a fixed order, then picks the first rule whose keyword occurs in the
ticket text. The KB query is the ticket text plus the customer's status from `get_customer`,
so a suspended customer's question finds the suspended-account article. Later slices only
append rules to RULES.

The refund rule is deliberately gullible: it believes an amount stated in the ticket ("refund
5000 EUR"), as a model following injected instructions would. The decision rules in `rules.py`
are what stop it, never this fake.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from agentic_ticket_workflow.models import Category, Decision, Priority


@dataclass(frozen=True)
class Rule:
    keywords: tuple[str, ...]
    category: Category
    priority: Priority
    action: Literal["reply", "escalate", "close", "refund"]
    needs_invoices: bool = False
    reason: str = "matched_rule"  # used by escalate / close rules


RULES: tuple[Rule, ...] = (
    Rule(("password", "log in", "login"), "account", "normal", "reply"),
    Rule(("outage", "errors", "down"), "technical", "urgent", "escalate", reason="possible_outage"),
    Rule(("locked", "suspended"), "account", "high", "reply", needs_invoices=True),
    Rule(("pizza", "lunch", "restaurant"), "other", "low", "close", reason="not_support_request"),
    # Last, so the earlier rules keep precedence.
    Rule(("refund", "charged twice"), "billing", "normal", "refund", needs_invoices=True),
)

# The first "<number> EUR" in the ticket text, e.g. "5000 EUR" or "49.00 eur".
_STATED_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*eur\b", re.IGNORECASE)


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
            status = (results["get_customer"] or {}).get("status", "")
            return _tool_call("search_kb", {"query": f"{text} {status}"})

        decision = self._decision(rule, results, text)
        return {"role": "assistant", "content": decision.model_dump_json(), "tool_calls": None}

    @staticmethod
    def _decision(rule: Rule | None, results: dict[str, Any], text: str) -> Decision:
        if rule is None:
            return Decision.model_validate(
                {
                    "category": "other",
                    "priority": "normal",
                    "action": {"type": "escalate", "reason": "no_matching_rule"},
                }
            )
        kb_hits = results["search_kb"]
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
        elif rule.action == "refund":
            invoices = results.get("get_invoices") or []
            if not invoices:
                action = {"type": "escalate", "reason": "no_invoice"}
            else:
                latest = max(invoices, key=lambda invoice: (invoice["month"], invoice["invoice_id"]))
                stated = _STATED_AMOUNT.search(text)
                amount = float(stated.group(1)) if stated else latest["amount_eur"]
                action = {"type": "refund", "invoice_id": latest["invoice_id"], "amount_eur": amount}
        else:
            action = {"type": rule.action, "reason": rule.reason}
        return Decision.model_validate({"category": rule.category, "priority": rule.priority, "action": action})
