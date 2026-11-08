"""Temporal activities: thin wrappers around the plain-Python core, with injected dependencies."""

import asyncio
import logging

from temporalio import activity
from temporalio.exceptions import ApplicationError

from agentic_ticket_workflow import agent, rules
from agentic_ticket_workflow.agent import ChatModel
from agentic_ticket_workflow.helpdesk import FakeHelpdesk
from agentic_ticket_workflow.models import ActionResult, ActRequest, CheckRequest, DecideResult, Ticket
from agentic_ticket_workflow.tools import load_data
from agentic_ticket_workflow.workflow import LLM_UNAVAILABLE, UNKNOWN_CUSTOMER, UNREADABLE_MODEL_ANSWER

# The SDK adapter adds a `temporal_activity` extra (IDs, attempt); the formatter reads it.
log = activity.LoggerAdapter(logging.getLogger("agentic_ticket_workflow.activities"), None)
log.activity_info_on_message = False


class TicketActivities:
    def __init__(self, model: ChatModel, helpdesk: FakeHelpdesk) -> None:
        self.model = model
        self.helpdesk = helpdesk

    @activity.defn(name="decide")
    async def decide(self, ticket: Ticket) -> DecideResult:
        # The model call may block (a real provider in S-08), so keep it off the event loop.
        try:
            result = await asyncio.to_thread(agent.decide, ticket, self.model)
        except agent.UnknownCustomer:
            log.info("unknown customer", extra={"reason_code": UNKNOWN_CUSTOMER})
            # Non-retryable: a retry can't create the customer. The type is the workflow's reason code.
            raise ApplicationError("customer not found", type=UNKNOWN_CUSTOMER, non_retryable=True) from None
        except agent.DisallowedValue as exc:
            log.info("decision value not allowed", extra={"reason_code": exc.code})
            # Non-retryable: asking again doesn't make the answer allowed. The workflow escalates with the code.
            raise ApplicationError("decision value not allowed", type=exc.code, non_retryable=True) from None
        except agent.UnreadableModelAnswer:
            log.info("model answer unreadable", extra={"reason_code": UNREADABLE_MODEL_ANSWER})
            # Retryable: a model may answer properly next time. The workflow escalates once retries run out.
            # Fixed message, `from None`: the cause would carry model text into Temporal history.
            raise ApplicationError("model answer unreadable", type=UNREADABLE_MODEL_ANSWER) from None
        except agent.ModelUnavailable as exc:
            log.info("model unavailable", extra={"reason_code": LLM_UNAVAILABLE, "error_type": exc.error_type})
            # Retryable: the provider may recover. A provider message may quote the request, so drop it.
            raise ApplicationError("model unavailable", type=LLM_UNAVAILABLE) from None
        except agent.ModelRequestRejected as exc:
            log.info("model request rejected", extra={"reason_code": LLM_UNAVAILABLE, "error_type": exc.error_type})
            # Non-retryable: asking again with the same key or model fails the same way. Escalate at once.
            raise ApplicationError("model request rejected", type=LLM_UNAVAILABLE, non_retryable=True) from None
        log.info("model decided", extra={"tools": [call.name for call in result.tool_calls]})
        return result

    @activity.defn(name="act")
    async def act(self, req: ActRequest) -> ActionResult:
        result = self.helpdesk.perform(req)
        log.info("helpdesk action done", extra={"action": result.action.type, "helpdesk_ref": result.helpdesk_ref})
        return result


@activity.defn(name="check")
async def check(req: CheckRequest) -> str | None:
    """Run the refund rules against the invoices loaded in code, never against the model's tool results."""
    violation = rules.check_decision(req.decision, req.customer_id, load_data("invoices"))
    log.info("decision checked", extra={"reason_code": violation})
    return violation
