import pytest

from agentic_ticket_workflow.tools import get_customer, get_invoices, run_tool, search_kb


def test_search_kb_ranks_password_article_first_for_t1(tickets):
    t1 = tickets["T-1"]
    hits = search_kb(f"{t1.subject} {t1.body}")
    assert hits[0]["article_id"] == "KB-1"


def test_get_customer_unknown_is_none():
    assert get_customer("C-999") is None


def test_get_customer_and_invoices():
    assert get_customer("C-200") == {"name": "Contoso Labs", "plan": "free", "status": "active"}
    assert {i["invoice_id"] for i in get_invoices("C-100")} == {"INV-1001", "INV-1002"}


def test_run_tool_unknown_name_raises():
    with pytest.raises(ValueError):
        run_tool("delete_everything", {})
