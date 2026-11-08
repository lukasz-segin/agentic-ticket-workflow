"""The durable per-ticket process (FR-001…FR-006): decide → check → approval wait (refunds only) → act.

The status is queryable. A valid refund waits at `awaiting_approval` until the `approve` Update records a
person's answer, for at most 24 h; then it is escalated with `approval_timeout`. The Update's validator
refuses any approval the ticket is not waiting for, including one that arrives at or after the deadline.
"""

import logging
from contextlib import suppress
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from agentic_ticket_workflow import rules
    from agentic_ticket_workflow.models import (
        Action,
        ActionResult,
        ActRequest,
        Approval,
        CheckRequest,
        CloseAction,
        DecideResult,
        EscalateAction,
        Step,
        Ticket,
        TicketStatus,
    )

DECIDE_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1), backoff_coefficient=2)
CHECK_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1), backoff_coefficient=2)
ACT_RETRY = RetryPolicy(
    maximum_attempts=5,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2,
    maximum_interval=timedelta(seconds=10),
)


# Non-retryable activity errors whose `ApplicationError.type` is one of these codes end in an
# escalation with that code as the reason, instead of failing the ticket (FR-005, FR-008). S-07 adds more.
UNKNOWN_CUSTOMER = "unknown_customer"
ESCALATE_ON_ERROR = frozenset({UNKNOWN_CUSTOMER}) | rules.ALLOWED_VALUE_CODES

# The `ApplicationError.type` an approval is refused with when the ticket isn't waiting for one (API: 409).
NOT_AWAITING_APPROVAL = "not_awaiting_approval"
# The close reason of a rejected refund; the approver's comment, if any, follows after ": ".
REFUND_REJECTED = "refund_rejected"
# How long a valid refund waits for a person's answer, from entering `awaiting_approval` (FR-006).
APPROVAL_TIMEOUT = timedelta(hours=24)
# The escalation reason (and timer name) of a refund nobody answered in time (US-04).
APPROVAL_TIMEOUT_CODE = "approval_timeout"

WORKFLOW_ID_PREFIX = "ticket-"


def workflow_id_for(ticket_id: str) -> str:
    return f"{WORKFLOW_ID_PREFIX}{ticket_id}"


def ticket_id_from(workflow_id: str) -> str | None:
    """Inverse of `workflow_id_for`; `None` for a workflow ID we did not mint."""
    if not workflow_id.startswith(WORKFLOW_ID_PREFIX):
        return None
    return workflow_id.removeprefix(WORKFLOW_ID_PREFIX) or None


# Our own logger (so LOG_LEVEL reaches it) wrapped in the SDK adapter: replay-safe, and the
# formatter takes the IDs from its `temporal_workflow` extra. Call it only from workflow code.
log = workflow.LoggerAdapter(logging.getLogger("agentic_ticket_workflow.workflow"), None)
log.workflow_info_on_message = False


@workflow.defn
class TicketWorkflow:
    def __init__(self) -> None:
        self._status: TicketStatus | None = None

    @workflow.run
    async def run(self, ticket: Ticket) -> TicketStatus:
        self._status = TicketStatus(
            ticket_id=ticket.ticket_id,
            workflow_id=workflow.info().workflow_id,
            step="received",
            steps=["received"],
        )
        log.info("step entered", extra={"step": "received"})

        self._enter("deciding")
        action: Action
        try:
            decided = await workflow.execute_activity(
                "decide",
                ticket,
                result_type=DecideResult,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=DECIDE_RETRY,
            )
        except ActivityError as err:
            code = err.cause.type if isinstance(err.cause, ApplicationError) else None
            if code is None or code not in ESCALATE_ON_ERROR:
                raise
            # No decision: the decision and tool calls stay empty in the status.
            if code in rules.ALLOWED_VALUE_CODES:
                self._status.violation = code
            action = EscalateAction(reason=code)
            log.info("escalated before decision", extra={"action": action.type, "reason_code": code})
        else:
            self._status.decision = decided.decision
            self._status.tool_calls = decided.tool_calls
            # Literal-typed fields and tool names only: messages, reasons and arguments may hold ticket text.
            log.info(
                "decision made",
                extra={
                    "category": decided.decision.category,
                    "priority": decided.decision.priority,
                    "action": decided.decision.action.type,
                    "tools": [call.name for call in decided.tool_calls],
                },
            )

            self._enter("checking")
            violation = await workflow.execute_activity(
                "check",
                CheckRequest(customer_id=ticket.customer_id, decision=decided.decision),
                result_type=str | None,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=CHECK_RETRY,
            )

            action = decided.decision.action
            if violation is not None:
                # Set before acting, so the broken rule shows while the helpdesk may still be retrying.
                self._status.violation = violation
                action = EscalateAction(reason=violation)
                log.info("rule broken", extra={"action": action.type, "reason_code": violation})
            elif action.type == "refund":
                # A refund is never issued without a human. Set the deadline, then enter the step (no
                # yield in between), so any query or validator that sees the wait also sees its deadline.
                self._status.approval_deadline = workflow.now() + APPROVAL_TIMEOUT
                self._enter("awaiting_approval")
                log.info("refund awaiting approval", extra={"action": action.type})
                # On timeout, decide below from the recorded approval, not from whether the timer fired.
                with suppress(TimeoutError):
                    await workflow.wait_condition(
                        lambda: self._status.approval is not None,
                        timeout=APPROVAL_TIMEOUT,
                        timeout_summary=APPROVAL_TIMEOUT_CODE,
                    )
                approval = self._status.approval
                if approval is None:
                    action = EscalateAction(reason=APPROVAL_TIMEOUT_CODE)
                    log.info(
                        "refund approval timed out", extra={"action": action.type, "reason_code": APPROVAL_TIMEOUT_CODE}
                    )
                elif not approval.approved:
                    reason = f"{REFUND_REJECTED}: {approval.comment}" if approval.comment else REFUND_REJECTED
                    action = CloseAction(reason=reason)

        self._enter("acting")
        self._status.result = await workflow.execute_activity(
            "act",
            ActRequest(
                ticket_id=ticket.ticket_id,
                idempotency_key=f"{self._status.workflow_id}:{action.type}",
                action=action,
            ),
            result_type=ActionResult,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=ACT_RETRY,
        )
        log.info(
            "action performed",
            extra={"action": self._status.result.action.type, "helpdesk_ref": self._status.result.helpdesk_ref},
        )

        self._enter("done")
        return self._status

    @workflow.update
    def approve(self, approval: Approval) -> None:
        """Record a person's answer to the waiting refund; the run coroutine acts on it.

        Synchronous on purpose: the SDK runs the validator and this handler with no yield in between,
        so the first approval wins. The re-check keeps that true even if this ever becomes async."""
        self._refuse_unless_awaiting_approval()
        self._status.approval = approval
        # The approver name is an audit field; the comment is free text and is never logged.
        log.info("refund approval received", extra={"approved": approval.approved, "approver": approval.approver})

    @approve.validator
    def _validate_approve(self, approval: Approval) -> None:
        self._refuse_unless_awaiting_approval()

    def _refuse_unless_awaiting_approval(self) -> None:
        # The deadline check matters when the worker was down past the deadline: the overdue timer and a
        # queued approval then arrive in one activation, and the SDK runs the Update before the timer, so
        # the step alone would still say "waiting". `workflow.now()` is that activation's time.
        status = self._status
        if (
            status is None
            or status.step != "awaiting_approval"
            or status.approval is not None
            or (status.approval_deadline is not None and workflow.now() >= status.approval_deadline)
        ):
            raise ApplicationError("ticket is not awaiting approval", type=NOT_AWAITING_APPROVAL, non_retryable=True)

    @workflow.query
    def status(self) -> TicketStatus:
        if self._status is None:
            raise RuntimeError("workflow has not started yet")
        return self._status

    def _enter(self, step: Step) -> None:
        assert self._status is not None
        self._status.step = step
        self._status.steps.append(step)
        log.info("step entered", extra={"step": step})
