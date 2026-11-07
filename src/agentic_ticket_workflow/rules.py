"""Decision rules (FR-005) in plain Python: each broken rule has a fixed code, used as the escalation reason.

The codes are constants, so they are safe to log and to raise. Never put the model's values, the refund
amount or the decision's reason text next to them: those are ticket text.
"""

from typing import Any

from pydantic import ValidationError

from agentic_ticket_workflow.models import Decision

# Allowed values. The `Decision` schema is the only list of them; these codes name its parse errors.
CATEGORY_NOT_ALLOWED = "category_not_allowed"
PRIORITY_NOT_ALLOWED = "priority_not_allowed"
ACTION_NOT_ALLOWED = "action_not_allowed"
ALLOWED_VALUE_CODES = frozenset({CATEGORY_NOT_ALLOWED, PRIORITY_NOT_ALLOWED, ACTION_NOT_ALLOWED})

# In field order: the first wrong field names the breach.
_ALLOWED_VALUE_ERRORS = (
    (("category",), "literal_error", CATEGORY_NOT_ALLOWED),
    (("priority",), "literal_error", PRIORITY_NOT_ALLOWED),
    (("action",), "union_tag_invalid", ACTION_NOT_ALLOWED),
)

# Refunds.
REFUND_INVOICE_NOT_FOUND = "refund_invoice_not_found"
REFUND_INVOICE_OF_OTHER_CUSTOMER = "refund_invoice_of_other_customer"
REFUND_AMOUNT_NOT_POSITIVE = "refund_amount_not_positive"
REFUND_AMOUNT_ABOVE_INVOICE = "refund_amount_above_invoice"


def disallowed_value(exc: ValidationError) -> str | None:
    """The code for a category, priority or action type outside the allowed set; `None` for other errors."""
    found = {(tuple(error["loc"]), error["type"]) for error in exc.errors()}
    return next((code for loc, kind, code in _ALLOWED_VALUE_ERRORS if (loc, kind) in found), None)


def check_decision(decision: Decision, customer_id: str, invoices: list[dict[str, Any]]) -> str | None:
    """The broken refund rule's code, or `None`. `invoices` is every invoice, not only the customer's."""
    action = decision.action
    if action.type != "refund":
        return None
    invoice = next((inv for inv in invoices if inv["invoice_id"] == action.invoice_id), None)
    if invoice is None:
        return REFUND_INVOICE_NOT_FOUND
    if invoice["customer_id"] != customer_id:
        return REFUND_INVOICE_OF_OTHER_CUSTOMER
    # Written as one chain so that NaN, which fails every comparison, is never accepted.
    if not 0 < action.amount_eur <= invoice["amount_eur"]:
        return REFUND_AMOUNT_NOT_POSITIVE if not action.amount_eur > 0 else REFUND_AMOUNT_ABOVE_INVOICE
    return None
