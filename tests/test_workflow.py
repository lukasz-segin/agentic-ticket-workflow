import uuid

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agentic_ticket_workflow.models import (
    ActionResult,
    ActRequest,
    Decision,
    DecideResult,
    EscalateAction,
    RefundAction,
    ReplyAction,
    Ticket,
    ToolCall,
)
from agentic_ticket_workflow.workflow import TicketWorkflow, workflow_id_for

T1_REPLY = ReplyAction(message="Reset your password: ...", article_ids=["KB-1"])


async def run_ticket(env: WorkflowEnvironment, ticket: Ticket, decision: Decision):
    """Run the workflow with fake decide/act activities; return (final status, status queried after completion, act requests)."""
    act_calls: list[ActRequest] = []

    @activity.defn(name="decide")
    async def fake_decide(_: Ticket) -> DecideResult:
        return DecideResult(decision=decision, tool_calls=[ToolCall(name="search_kb", arguments={"query": "x"})])

    @activity.defn(name="act")
    async def fake_act(req: ActRequest) -> ActionResult:
        act_calls.append(req)
        return ActionResult(action=req.action, helpdesk_ref="HD-1")

    task_queue = str(uuid.uuid4())
    async with Worker(env.client, task_queue=task_queue, workflows=[TicketWorkflow],
                      activities=[fake_decide, fake_act]):
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
    assert status.steps == ["received", "deciding", "acting", "done"]
    assert status.workflow_id == "ticket-T-1"
    assert status.decision == decision
    assert status.result.action == T1_REPLY
    assert [call.name for call in status.tool_calls] == ["search_kb"]
    assert len(act_calls) == 1
    assert act_calls[0].idempotency_key == "ticket-T-1:reply"
    assert queried == status


async def test_refund_is_escalated_until_approval_exists(env, tickets):
    refund = RefundAction(invoice_id="INV-1", amount_eur=10.0)
    decision = Decision(category="billing", priority="normal", action=refund)
    status, _, act_calls = await run_ticket(env, tickets["T-1"], decision)

    assert len(act_calls) == 1
    assert act_calls[0].action == EscalateAction(reason="refund_needs_approval")
    assert act_calls[0].idempotency_key == "ticket-T-1:escalate"
    assert status.decision.action.type == "refund"
    assert status.result.action == EscalateAction(reason="refund_needs_approval")
