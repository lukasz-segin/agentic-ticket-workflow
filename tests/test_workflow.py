import asyncio
import json
import math
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError, WorkflowHandle, WorkflowQueryFailedError, WorkflowUpdateFailedError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agentic_ticket_workflow.activities import TicketActivities, check
from agentic_ticket_workflow.fake_llm import FakeChatModel
from agentic_ticket_workflow.helpdesk import FakeHelpdesk
from agentic_ticket_workflow.models import (
    ActionResult,
    ActRequest,
    Approval,
    CloseAction,
    DecideResult,
    Decision,
    EscalateAction,
    RefundAction,
    ReplyAction,
    Ticket,
    TicketStatus,
    ToolCall,
)
from agentic_ticket_workflow.workflow import (
    APPROVAL_TIMEOUT,
    NOT_AWAITING_APPROVAL,
    TicketWorkflow,
    ticket_id_from,
    workflow_id_for,
)
from tests.fakes import ScriptedRandom

T1_REPLY = ReplyAction(message="Reset your password: ...", article_ids=["KB-1"])
# A valid refund: C-100's own invoice, for no more than its amount.
T2_REFUND = RefundAction(invoice_id="INV-1002", amount_eur=49.0)
T2_DECISION = Decision(category="billing", priority="normal", action=T2_REFUND)


def fake_activities(
    decision: Decision | ApplicationError,
    act_calls: list[ActRequest],
    decide_calls: list[Ticket] | None = None,
    act_gate: asyncio.Event | None = None,
):
    """Fake decide/act plus the real check. An `ApplicationError` is raised by `decide`; `act` records
    each request and, given a gate, blocks until it is set, so the workflow stays running at `acting`."""

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
        if act_gate is not None:
            await act_gate.wait()
        return ActionResult(action=req.action, helpdesk_ref="HD-1")

    return [fake_decide, check, fake_act]


def worker(env: WorkflowEnvironment, task_queue: str, activities, **options) -> Worker:
    return Worker(env.client, task_queue=task_queue, workflows=[TicketWorkflow], activities=activities, **options)


@asynccontextmanager
async def started(env: WorkflowEnvironment, ticket: Ticket, activities, task_queue: str | None = None, **options):
    """Start the ticket's workflow on a fresh worker; the worker runs until the block ends.

    `options` go to the `Worker`; `task_queue` lets a later worker pick the workflow up."""
    task_queue = task_queue or str(uuid.uuid4())
    async with worker(env, task_queue, activities, **options):
        yield await env.client.start_workflow(
            TicketWorkflow.run, ticket, id=workflow_id_for(ticket.ticket_id), task_queue=task_queue
        )


async def wait_for_step(handle: WorkflowHandle, step: str) -> TicketStatus:
    """Poll the status query until the workflow is at `step`."""
    for _ in range(200):
        try:
            status = await handle.query(TicketWorkflow.status)
        except WorkflowQueryFailedError:  # not started yet
            status = None
        if status is not None and status.step == step:
            return status
        await asyncio.sleep(0.05)
    raise AssertionError(f"workflow never reached step {step!r}")


async def assert_refused(handle: WorkflowHandle, approval: Approval) -> None:
    with pytest.raises(WorkflowUpdateFailedError) as refused:
        await handle.execute_update(TicketWorkflow.approve, approval)
    assert isinstance(refused.value.cause, ApplicationError)
    assert refused.value.cause.type == NOT_AWAITING_APPROVAL


async def skip_to_deadline(env: WorkflowEnvironment, handle: WorkflowHandle, waiting: TicketStatus) -> None:
    """Advance the test server's clock to exactly the approval deadline, which fires the timer.

    Only while the workflow waits: no margin, so a gated `act` never sits through skipped time (and
    its 30 s timeout) afterwards."""
    await env.sleep(waiting.approval_deadline - await env.get_current_time(handle))


async def run_ticket(
    env: WorkflowEnvironment,
    ticket: Ticket,
    decision: Decision | ApplicationError,
    decide_calls: list[Ticket] | None = None,
):
    """Run the workflow to completion with fake decide/act activities.

    Returns (final status, status queried after completion, act requests)."""
    act_calls: list[ActRequest] = []
    async with started(env, ticket, fake_activities(decision, act_calls, decide_calls)) as handle:
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


async def test_approved_refund_is_issued_exactly_once_despite_helpdesk_failures(env, tickets):
    # Attempt 1: fail roll (0.0 < 0.5), then the "after recording" branch (0.9 >= 0.5): the refund is
    # recorded and the response is lost. Attempt 2 (a Temporal retry): roll passes (0.9), the known key
    # returns the recorded result instead of refunding again.
    helpdesk = FakeHelpdesk(0.5, rng=ScriptedRandom([0.0, 0.9, 0.9]))
    acts = TicketActivities(FakeChatModel(), helpdesk)
    approval = Approval(approved=True, approver="Ann", comment="duplicate confirmed")

    async with started(env, tickets["T-2"], [acts.decide, check, acts.act]) as handle:
        waiting = await wait_for_step(handle, "awaiting_approval")
        assert waiting.violation is None
        assert waiting.decision.action == T2_REFUND
        assert waiting.result is None
        assert helpdesk.performed == {}

        await handle.execute_update(TicketWorkflow.approve, approval)
        status = await handle.result()

    assert status.steps == ["received", "deciding", "checking", "awaiting_approval", "acting", "done"]
    assert status.result == ActionResult(action=T2_REFUND, helpdesk_ref="HD-1")
    assert status.approval == approval
    assert list(helpdesk.performed) == ["ticket-T-2:refund"]
    with pytest.raises(StopIteration):  # the whole script was used: both attempts happened
        helpdesk.rng.random()


async def test_concurrent_approve_and_reject_accept_exactly_one(env, tickets):
    act_calls: list[ActRequest] = []
    async with started(env, tickets["T-2"], fake_activities(T2_DECISION, act_calls)) as handle:
        await wait_for_step(handle, "awaiting_approval")
        outcomes = await asyncio.gather(
            handle.execute_update(TicketWorkflow.approve, Approval(approved=True)),
            handle.execute_update(TicketWorkflow.approve, Approval(approved=False)),
            return_exceptions=True,
        )
        status = await handle.result()

    accepted = [i for i, outcome in enumerate(outcomes) if not isinstance(outcome, BaseException)]
    assert len(accepted) == 1
    refused = outcomes[1 - accepted[0]]
    assert isinstance(refused, WorkflowUpdateFailedError)
    assert refused.cause.type == NOT_AWAITING_APPROVAL
    approved = accepted[0] == 0
    assert status.approval.approved is approved
    assert len(act_calls) == 1
    assert act_calls[0].action.type == ("refund" if approved else "close")


@pytest.mark.parametrize(
    ("comment", "reason"),
    [("not a duplicate", "refund_rejected: not a duplicate"), (None, "refund_rejected")],
)
async def test_rejected_refund_closes_with_the_comment(env, tickets, comment, reason):
    act_calls: list[ActRequest] = []
    async with started(env, tickets["T-2"], fake_activities(T2_DECISION, act_calls)) as handle:
        await wait_for_step(handle, "awaiting_approval")
        await handle.execute_update(TicketWorkflow.approve, Approval(approved=False, approver="Ann", comment=comment))
        status = await handle.result()

    assert status.steps == ["received", "deciding", "checking", "awaiting_approval", "acting", "done"]
    assert status.decision == T2_DECISION  # the rejected proposal stays visible
    assert len(act_calls) == 1  # no refund
    assert act_calls[0].action == CloseAction(reason=reason)
    assert act_calls[0].idempotency_key == "ticket-T-2:close"
    assert status.result.action == CloseAction(reason=reason)
    assert status.approval == Approval(approved=False, approver="Ann", comment=comment)


async def test_second_approval_is_refused(env, tickets):
    act_calls: list[ActRequest] = []
    gate = asyncio.Event()
    async with started(env, tickets["T-2"], fake_activities(T2_DECISION, act_calls, act_gate=gate)) as handle:
        await wait_for_step(handle, "awaiting_approval")
        await handle.execute_update(TicketWorkflow.approve, Approval(approved=True))
        await wait_for_step(handle, "acting")  # still running: act is blocked
        await assert_refused(handle, Approval(approved=True))
        await assert_refused(handle, Approval(approved=False))
        gate.set()
        status = await handle.result()

    assert status.approval == Approval(approved=True)
    assert len(act_calls) == 1
    assert act_calls[0].action == T2_REFUND


async def test_approval_for_a_ticket_not_awaiting_is_refused(env, tickets):
    act_calls: list[ActRequest] = []
    gate = asyncio.Event()
    decision = Decision(category="account", priority="normal", action=T1_REPLY)
    async with started(env, tickets["T-1"], fake_activities(decision, act_calls, act_gate=gate)) as handle:
        await wait_for_step(handle, "acting")
        await assert_refused(handle, Approval(approved=True))
        gate.set()
        status = await handle.result()

    assert "awaiting_approval" not in status.steps
    assert status.approval is None
    assert status.result.action == T1_REPLY


TIMED_OUT = EscalateAction(reason="approval_timeout")


async def test_unanswered_refund_is_escalated_after_24h(env, tickets):
    act_calls: list[ActRequest] = []
    async with started(env, tickets["T-2"], fake_activities(T2_DECISION, act_calls)) as handle:
        waiting = await wait_for_step(handle, "awaiting_approval")
        assert waiting.approval_deadline is not None
        status = await handle.result()  # nothing else to do: the test server skips the 24 h

    assert status.steps == ["received", "deciding", "checking", "awaiting_approval", "acting", "done"]
    assert status.decision == T2_DECISION  # the unanswered proposal stays visible
    assert status.violation is None  # a timeout is not a broken rule
    assert status.approval is None
    assert status.approval_deadline == waiting.approval_deadline
    assert len(act_calls) == 1  # no refund
    assert act_calls[0].action == TIMED_OUT
    assert act_calls[0].idempotency_key == "ticket-T-2:escalate"
    assert status.result.action == TIMED_OUT


async def test_late_approval_is_refused_and_never_refunds(env, tickets):
    act_calls: list[ActRequest] = []
    gate = asyncio.Event()
    async with started(env, tickets["T-2"], fake_activities(T2_DECISION, act_calls, act_gate=gate)) as handle:
        waiting = await wait_for_step(handle, "awaiting_approval")
        await skip_to_deadline(env, handle, waiting)
        await wait_for_step(handle, "acting")  # still running: act is blocked
        await assert_refused(handle, Approval(approved=True))
        await assert_refused(handle, Approval(approved=False))
        gate.set()
        status = await handle.result()

    assert status.approval is None
    assert len(act_calls) == 1
    assert act_calls[0].action == TIMED_OUT


async def test_approval_just_before_the_deadline_is_honoured(env, tickets):
    act_calls: list[ActRequest] = []
    async with started(env, tickets["T-2"], fake_activities(T2_DECISION, act_calls)) as handle:
        await wait_for_step(handle, "awaiting_approval")
        await env.sleep(APPROVAL_TIMEOUT - timedelta(minutes=1))
        await handle.execute_update(TicketWorkflow.approve, Approval(approved=True))
        status = await handle.result()

    assert status.approval == Approval(approved=True)
    assert len(act_calls) == 1
    assert act_calls[0].action == T2_REFUND


async def test_approval_queued_during_worker_downtime_after_the_deadline_is_refused(env, tickets):
    # The worker is down when the deadline passes and an approval is queued meanwhile. The new worker gets
    # the overdue timer and the Update together, and the SDK runs the Update first, while the step still
    # says "awaiting_approval": only the validator's deadline check refuses it.
    act_calls: list[ActRequest] = []
    activities = fake_activities(T2_DECISION, act_calls)
    task_queue = str(uuid.uuid4())
    # No workflow cache: otherwise the test server keeps routing the workflow's tasks to this worker's sticky
    # queue after it stops, and the next worker never sees them.
    async with started(env, tickets["T-2"], activities, task_queue=task_queue, max_cached_workflows=0) as handle:
        waiting = await wait_for_step(handle, "awaiting_approval")

    # Skip first: the test server doesn't skip time while an Update waits for a worker. The timer fires on
    # the server meanwhile; its workflow task stays pending until a worker comes back.
    await skip_to_deadline(env, handle, waiting)
    late = asyncio.create_task(handle.execute_update(TicketWorkflow.approve, Approval(approved=True)))
    await asyncio.sleep(0.5)  # let the Update reach the server; with no worker it stays pending there
    assert not late.done()

    async with worker(env, task_queue, activities):
        with pytest.raises(WorkflowUpdateFailedError) as refused:
            await late
        status = await handle.result()

    assert refused.value.cause.type == NOT_AWAITING_APPROVAL
    assert status.approval is None
    assert len(act_calls) == 1  # no refund
    assert act_calls[0].action == TIMED_OUT


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


@pytest.mark.parametrize(
    ("amount", "code"),
    [(math.nan, "refund_amount_not_positive"), (math.inf, "refund_amount_above_invoice")],
)
async def test_non_finite_refund_crosses_temporal_and_is_escalated(env, tickets, amount, code):
    # Pydantic's default JSON for NaN/inf is null, which would strand the workflow before the check.
    decision = Decision(
        category="billing", priority="normal", action=RefundAction(invoice_id="INV-1002", amount_eur=amount)
    )
    status, queried, act_calls = await run_ticket(env, tickets["T-2"], decision)

    assert status.steps == ["received", "deciding", "checking", "acting", "done"]
    assert status.violation == code
    proposed = status.decision.action.amount_eur
    assert math.isnan(proposed) if math.isnan(amount) else proposed == amount
    assert len(act_calls) == 1
    assert act_calls[0].action == EscalateAction(reason=code)
    assert queried.violation == code


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


async def test_t6_injection_is_escalated_with_the_broken_rule_through_the_real_activities(env, tickets):
    status = await run_real(env, tickets["T-6"])
    assert status.step == "done"
    assert status.violation == "refund_amount_above_invoice"
    # The model's proposal stays visible; only the escalation is performed (run_real checks it is one action).
    assert status.decision.action == RefundAction(invoice_id="INV-1002", amount_eur=5000.0)
    assert status.result.action == EscalateAction(reason="refund_amount_above_invoice")
    assert "awaiting_approval" not in status.steps  # a rule-breaking refund never waits for a person


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
