"""The durable per-ticket process (FR-001…FR-005): decide → check → refund guard → act, with a queryable status."""

import logging
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
        CheckRequest,
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
                # No approval wait until S-05: a refund is never issued without a human.
                action = EscalateAction(reason="refund_needs_approval")
                log.info("refund held for approval", extra={"action": action.type, "reason_code": action.reason})

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
