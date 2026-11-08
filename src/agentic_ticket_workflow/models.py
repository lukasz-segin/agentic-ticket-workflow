"""Domain types shared by the agent loop, the workflow and the API. Pydantic only."""

import math
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, PlainSerializer

# IDs become part of workflow IDs and helpdesk keys: keep them short and plain.
IDENTIFIER_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
Identifier = Annotated[str, Field(pattern=IDENTIFIER_PATTERN)]

Category = Literal["account", "billing", "technical", "other"]
Priority = Literal["low", "normal", "high", "urgent"]
# A valid refund waits at "awaiting_approval" between "checking" and "acting". A ticket whose action
# the helpdesk never confirmed ends at "failed" instead of "done" (FR-007).
Step = Literal["received", "deciding", "checking", "awaiting_approval", "acting", "done", "failed"]


class Ticket(BaseModel):
    ticket_id: Identifier
    customer_id: Identifier
    # Bounded: the text is stored in Temporal history and, from S-08, sent to the model.
    subject: Annotated[str, Field(min_length=1, max_length=200)]
    body: Annotated[str, Field(min_length=1, max_length=10_000)]


class ReplyAction(BaseModel):
    type: Literal["reply"] = "reply"
    message: str
    article_ids: list[str]


def _json_float(value: float) -> float | str:
    # Pydantic writes NaN and infinity as JSON null, which doesn't parse back as a float, so a model's
    # NaN proposal could never cross Temporal to the rule check. As "nan" / "inf" / "-inf" they parse
    # back to the same float, and the check names the broken rule. Set on the field, not the model's
    # config, because that config only takes effect on the outermost model being serialized.
    return value if math.isfinite(value) else str(value)


class RefundAction(BaseModel):
    type: Literal["refund"] = "refund"
    invoice_id: str
    amount_eur: Annotated[float, PlainSerializer(_json_float, when_used="json")]


class EscalateAction(BaseModel):
    type: Literal["escalate"] = "escalate"
    reason: str


class CloseAction(BaseModel):
    type: Literal["close"] = "close"
    reason: str


Action = Annotated[
    ReplyAction | RefundAction | EscalateAction | CloseAction,
    Field(discriminator="type"),
]


class Decision(BaseModel):
    category: Category
    priority: Priority
    action: Action


class ToolCall(BaseModel):
    # Arguments may contain ticket text (search_kb's query is subject + body): never log them (FR-010).
    name: str
    arguments: dict[str, Any]


class DecideResult(BaseModel):
    decision: Decision
    tool_calls: list[ToolCall]


class CheckRequest(BaseModel):
    customer_id: str
    decision: Decision


class ActRequest(BaseModel):
    ticket_id: str
    idempotency_key: str
    action: Action


class ActionResult(BaseModel):
    action: Action
    helpdesk_ref: str


class Approval(BaseModel):
    """A person's answer to a waiting refund: the Update argument, the API body and the status field.

    Bounded because it is stored in Temporal history; `approver` is also logged, `comment` never is."""

    approved: bool
    approver: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    comment: Annotated[str, Field(min_length=1, max_length=1000)] | None = None


class TicketStatus(BaseModel):
    ticket_id: str
    workflow_id: str
    step: Step
    steps: list[Step]
    tool_calls: list[ToolCall] = []
    decision: Decision | None = None
    # The code of the decision rule the model broke (FR-005); the ticket is then escalated with it.
    violation: str | None = None
    # Set when a valid refund starts waiting: an answer must reach the workflow before this time,
    # otherwise the ticket is escalated with `approval_timeout` (FR-006, US-04).
    approval_deadline: datetime | None = None
    approval: Approval | None = None
    result: ActionResult | None = None
    # Set when the ticket fails (FR-007), e.g. `helpdesk_unavailable`: the helpdesk never confirmed the action
    # (it may or may not have been carried out, but never twice: retries reuse one idempotency key).
    failure_reason: str | None = None
