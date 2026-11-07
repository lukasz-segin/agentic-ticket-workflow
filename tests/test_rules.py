import math

import pytest
from pydantic import ValidationError

from agentic_ticket_workflow.models import CloseAction, Decision, EscalateAction, RefundAction, ReplyAction
from agentic_ticket_workflow.rules import check_decision, disallowed_value
from agentic_ticket_workflow.tools import load_data

VALID = {"category": "billing", "priority": "normal", "action": {"type": "close", "reason": "x"}}
INVOICES = load_data("invoices")


def parse_error(answer: dict) -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        Decision.model_validate(answer)
    return caught.value


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"category": "refunds"}, "category_not_allowed"),
        ({"priority": "asap"}, "priority_not_allowed"),
        ({"priority": 3}, "priority_not_allowed"),  # any value outside the set, whatever its type
        ({"action": {"type": "transfer", "reason": "x"}}, "action_not_allowed"),
        # Several wrong: the first field in order names the breach.
        ({"category": "refunds", "priority": "asap", "action": {"type": "transfer"}}, "category_not_allowed"),
        ({"priority": "asap", "action": {"type": "transfer"}}, "priority_not_allowed"),
        # An allowed-value breach wins over other errors in the same answer.
        ({"category": "refunds", "action": {"type": "refund", "invoice_id": "INV-1"}}, "category_not_allowed"),
    ],
)
def test_disallowed_value_names_the_field(changes, code):
    assert disallowed_value(parse_error({**VALID, **changes})) == code


@pytest.mark.parametrize(
    "answer",
    [
        {**VALID, "action": {"reason": "x"}},  # missing action tag
        {**VALID, "action": {"type": "refund", "invoice_id": "INV-1"}},  # missing field
        {"category": "billing", "priority": "normal"},  # missing action
    ],
)
def test_other_parse_errors_are_not_a_disallowed_value(answer):
    assert disallowed_value(parse_error(answer)) is None


def refund(invoice_id: str, amount: float) -> Decision:
    return Decision(
        category="billing", priority="normal", action=RefundAction(invoice_id=invoice_id, amount_eur=amount)
    )


def test_refund_up_to_the_invoice_amount_passes():
    # INV-1002 is C-100's, for 49.0 EUR: refunding exactly the invoice amount is allowed.
    assert check_decision(refund("INV-1002", 49.0), "C-100", INVOICES) is None
    assert check_decision(refund("INV-1002", 0.01), "C-100", INVOICES) is None


@pytest.mark.parametrize(
    "action",
    [ReplyAction(message="m", article_ids=["KB-1"]), EscalateAction(reason="r"), CloseAction(reason="r")],
)
def test_non_refund_actions_pass(action):
    assert check_decision(Decision(category="other", priority="low", action=action), "C-100", INVOICES) is None


@pytest.mark.parametrize(
    ("invoice_id", "amount", "code"),
    [
        ("INV-9999", 10.0, "refund_invoice_not_found"),
        ("INV-3001", 10.0, "refund_invoice_of_other_customer"),
        ("INV-1002", 0.0, "refund_amount_not_positive"),
        ("INV-1002", -1.0, "refund_amount_not_positive"),
        ("INV-1002", math.nan, "refund_amount_not_positive"),
        ("INV-1002", 49.01, "refund_amount_above_invoice"),
        ("INV-1002", 5000.0, "refund_amount_above_invoice"),
        # Rule order: the invoice is checked before the amount.
        ("INV-9999", -1.0, "refund_invoice_not_found"),
        ("INV-3001", 5000.0, "refund_invoice_of_other_customer"),
    ],
)
def test_refund_rule_broken(invoice_id, amount, code):
    assert check_decision(refund(invoice_id, amount), "C-100", INVOICES) == code
