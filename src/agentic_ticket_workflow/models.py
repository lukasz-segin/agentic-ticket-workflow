"""Domain types shared by the agent loop, the workflow and the API. Pydantic only."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

NonEmpty = Annotated[str, Field(min_length=1)]

Category = Literal["account", "billing", "technical", "other"]
Priority = Literal["low", "normal", "high", "urgent"]
# Later slices add values (e.g. waiting for approval).
Step = Literal["received", "deciding", "acting", "done"]


class Ticket(BaseModel):
    ticket_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    customer_id: NonEmpty
    subject: NonEmpty
    body: NonEmpty


class ReplyAction(BaseModel):
    type: Literal["reply"] = "reply"
    message: str
    article_ids: list[str]


class RefundAction(BaseModel):
    type: Literal["refund"] = "refund"
    invoice_id: str
    amount_eur: float


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
    name: str
    arguments: dict[str, Any]


class DecideResult(BaseModel):
    decision: Decision
    tool_calls: list[ToolCall]


class ActRequest(BaseModel):
    ticket_id: str
    idempotency_key: str
    action: Action


class ActionResult(BaseModel):
    action: Action
    helpdesk_ref: str


class TicketStatus(BaseModel):
    ticket_id: str
    workflow_id: str
    step: Step
    steps: list[Step]
    tool_calls: list[ToolCall] = []
    decision: Decision | None = None
    result: ActionResult | None = None
