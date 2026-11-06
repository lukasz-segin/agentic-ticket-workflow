"""The lookup tools the model may call, run in plain code over the packaged sample data."""

import json
import re
from functools import cache
from importlib.resources import files
from typing import Any


@cache
def load_data(name: str) -> list[dict[str, Any]]:
    """Load one packaged JSON array (customers, invoices, kb, tickets)."""
    return json.loads((files("agentic_ticket_workflow") / "data" / f"{name}.json").read_text("utf-8"))


def get_customer(customer_id: str) -> dict[str, Any] | None:
    for customer in load_data("customers"):
        if customer["customer_id"] == customer_id:
            return {key: customer[key] for key in ("name", "plan", "status")}
    return None


def get_invoices(customer_id: str) -> list[dict[str, Any]]:
    return [invoice for invoice in load_data("invoices") if invoice["customer_id"] == customer_id]


def search_kb(query: str) -> list[dict[str, Any]]:
    """Rank articles by how many query words (4+ letters) occur in their title and text."""
    words = {word for word in re.findall(r"[a-z]+", query.lower()) if len(word) >= 4}
    scored = []
    for article in load_data("kb"):
        haystack = f"{article['title']} {article['text']}".lower()
        score = sum(1 for word in words if word in haystack)
        if score:
            scored.append((score, article))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["article_id"]))
    return [article for _, article in scored]


def _schema(name: str, description: str, param: str, param_description: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {param: {"type": "string", "description": param_description}},
                "required": [param],
            },
        },
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    _schema("get_customer", "Look up a customer's name, plan and status.", "customer_id", "e.g. C-100"),
    _schema("get_invoices", "List a customer's invoices.", "customer_id", "e.g. C-100"),
    _schema("search_kb", "Search the knowledge base articles.", "query", "Free-text search query"),
]

_TOOLS = {"get_customer": get_customer, "get_invoices": get_invoices, "search_kb": search_kb}


def run_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name not in _TOOLS:
        raise ValueError(f"unknown tool: {name}")
    return _TOOLS[name](**arguments)
