import json
import uuid

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agentic_ticket_workflow.activities import TicketActivities, check
from agentic_ticket_workflow.fake_llm import FakeChatModel
from agentic_ticket_workflow.helpdesk import FakeHelpdesk
from agentic_ticket_workflow.models import (
    ActionResult,
    ActRequest,
    CloseAction,
    DecideResult,
    Decision,
    EscalateAction,
    RefundAction,
    ReplyAction,
    Ticket,
    ToolCall,
)
from agentic_ticket_workflow.workflow import TicketWorkflow, ticket_id_from, workflow_id_for

T1_REPLY = ReplyAction(message="Reset your password: ...", article_ids=["KB-1"])


async def run_ticket(
    env: WorkflowEnvironment,
    ticket: Ticket,
    decision: Decision | ApplicationError,
    decide_calls: list[Ticket] | None = None,
):
    """Run the workflow with fake decide/act activities. An `ApplicationError` is raised by `decide`.

    Returns (final status, status queried after completion, act requests)."""
    act_calls: list[ActRequest] = []

    @activity.defn(name="decide")
    async def fake_decide(t: Ticket) -> DecideResult:
        if decide_calls is not None:
            decide_calls.append(t)
        if isinstance(decision, ApplicationError):
            raise decision
        return DecideResult(decision=decision, tool_calls=[ToolCall(name="search_kb", arguments={"query": "x"})])

    @activity.defn(name="act")
    async def fake_act(req: ActRequest) -> ActionResult:
        act_calls.append(req)
        return ActionResult(action=req.action, helpdesk_ref="HD-1")

    task_queue = str(uuid.uuid4())
    async with Worker(
        env.client, task_queue=task_queue, workflows=[TicketWorkflow], activities=[fake_decide, check, fake_act]
    ):
        handle = await env.client.start_workflow(
            TicketWorkflow.run, ticket, id=workflow_id_for(ticket.ticket_id), task_queue=task_queue
        )
        status = await handle.result()
        queried = await handle.query(TicketWorkflow.status)
    return status, queried, act_calls


async def test_answered_ticket(env, tickets):
    decision = Decision(category="account", priority="normal", action=T1_REPLY)
    status, queried, act_calls = await run_ticket(env, tickets["T-1"], decision)

    assert status.step == "done"
    assert status.steps == ["received", "deciding", "checking", "acting", "done"]
    assert status.workflow_id == "ticket-T-1"
    assert status.decision == decision
    assert status.violation is None
    assert status.result.action == T1_REPLY
    assert [call.name for call in status.tool_calls] == ["search_kb"]
    assert len(act_calls) == 1
    assert act_calls[0].idempotency_key == "ticket-T-1:reply"
    assert queried == status


async def test_refund_is_escalated_until_approval_exists(env, tickets):
    # A valid refund: C-100's own invoice, for no more than its amount.
    refund = RefundAction(invoice_id="INV-1002", amount_eur=49.0)
    decision = Decision(category="billing", priority="normal", action=refund)
    status, _, act_calls = await run_ticket(env, tickets["T-2"], decision)

    assert status.violation is None
    assert len(act_calls) == 1
    assert act_calls[0].action == EscalateAction(reason="refund_needs_approval")
    assert act_calls[0].idempotency_key == "ticket-T-2:escalate"
    assert status.decision.action.type == "refund"
    assert status.result.action == EscalateAction(reason="refund_needs_approval")


async def test_refund_breaking_a_rule_is_escalated_with_the_rule(env, tickets):
    # T-6's injection asks for 5000 EUR; the check stops it whatever the model proposed.
    refund = RefundAction(invoice_id="INV-1002", amount_eur=5000.0)
    decision = Decision(category="billing", priority="normal", action=refund)
    status, queried, act_calls = await run_ticket(env, tickets["T-6"], decision)

    assert status.step == "done"
    assert status.steps == ["received", "deciding", "checking", "acting", "done"]
    assert status.violation == "refund_amount_above_invoice"
    assert status.decision == decision
    assert len(act_calls) == 1
    assert act_calls[0].action == EscalateAction(reason="refund_amount_above_invoice")
    assert act_calls[0].idempotency_key == "ticket-T-6:escalate"
    assert status.result.action == EscalateAction(reason="refund_amount_above_invoice")
    assert queried == status


async def test_disallowed_value_escalates_without_a_decision_or_retry(env, tickets):
    decide_calls: list[Ticket] = []
    error = ApplicationError("decision value not allowed", type="action_not_allowed", non_retryable=True)
    status, _, act_calls = await run_ticket(env, tickets["T-1"], error, decide_calls)

    assert len(decide_calls) == 1
    assert status.steps == ["received", "deciding", "acting", "done"]
    assert status.violation == "action_not_allowed"
    assert status.decision is None
    assert len(act_calls) == 1
    assert act_calls[0].action == EscalateAction(reason="action_not_allowed")


class AsapModel:
    """Answers at once with a priority outside the allowed set."""

    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        answer = {"category": "account", "priority": "asap", "action": {"type": "close", "reason": "x"}}
        return {"role": "assistant", "content": json.dumps(answer), "tool_calls": None}


async def test_disallowed_value_from_the_real_decide_activity_is_escalated(env, tickets):
    model = AsapModel()
    acts = TicketActivities(model, FakeHelpdesk(0.0))
    task_queue = str(uuid.uuid4())
    async with Worker(
        env.client, task_queue=task_queue, workflows=[TicketWorkflow], activities=[acts.decide, check, acts.act]
    ):
        status = await env.client.execute_workflow(
            TicketWorkflow.run, tickets["T-1"], id=workflow_id_for("T-1"), task_queue=task_queue
        )

    assert model.calls == 1  # not retried
    assert status.violation == "priority_not_allowed"
    assert status.decision is None
    assert status.result.action == EscalateAction(reason="priority_not_allowed")


async def test_unknown_customer_escalates_without_a_decision_or_retry(env, tickets):
    decide_calls: list[Ticket] = []
    error = ApplicationError("customer not found", type="unknown_customer", non_retryable=True)
    status, _, act_calls = await run_ticket(env, tickets["T-7"], error, decide_calls)

    assert len(decide_calls) == 1
    assert status.step == "done"
    assert status.steps == ["received", "deciding", "acting", "done"]
    assert status.decision is None
    assert status.violation is None
    assert status.tool_calls == []
    assert len(act_calls) == 1
    assert act_calls[0].action == EscalateAction(reason="unknown_customer")
    assert act_calls[0].idempotency_key == "ticket-T-7:escalate"


async def test_unlisted_activity_error_still_fails_the_workflow(env, tickets):
    error = ApplicationError("boom", type="something_else", non_retryable=True)
    with pytest.raises(WorkflowFailureError):
        await run_ticket(env, tickets["T-1"], error)


@pytest.mark.parametrize(
    ("ticket_id", "action"),
    [
        ("T-3", EscalateAction(reason="possible_outage")),
        ("T-5", CloseAction(reason="not_support_request")),
        ("T-7", EscalateAction(reason="unknown_customer")),
    ],
)
async def test_example_tickets_through_the_real_activities(env, tickets, ticket_id, action):
    status = await run_real(env, tickets[ticket_id])
    assert status.step == "done"
    assert status.result.action == action
    assert (status.decision is None) == (ticket_id == "T-7")


async def test_t4_is_answered_with_kb4_through_the_real_activities(env, tickets):
    status = await run_real(env, tickets["T-4"])
    assert status.step == "done"
    assert status.result.action.type == "reply"
    assert status.result.action.article_ids == ["KB-4"]


async def run_real(env: WorkflowEnvironment, ticket: Ticket):
    """Run the workflow through the real activities: fake model, helpdesk that never fails."""
    acts = TicketActivities(FakeChatModel(), FakeHelpdesk(0.0))
    task_queue = str(uuid.uuid4())
    async with Worker(
        env.client, task_queue=task_queue, workflows=[TicketWorkflow], activities=[acts.decide, check, acts.act]
    ):
        status = await env.client.execute_workflow(
            TicketWorkflow.run, ticket, id=workflow_id_for(ticket.ticket_id), task_queue=task_queue
        )
    assert len(acts.helpdesk.performed) == 1
    return status


@pytest.mark.parametrize(
    ("workflow_id", "ticket_id"),
    [
        ("ticket-T-1", "T-1"),
        (workflow_id_for("T-7"), "T-7"),
        ("cron-job-1", None),
        ("", None),
        ("ticket", None),
        ("ticket-", None),
    ],
)
def test_ticket_id_from_inverts_workflow_id_for(workflow_id, ticket_id):
    assert ticket_id_from(workflow_id) == ticket_id
