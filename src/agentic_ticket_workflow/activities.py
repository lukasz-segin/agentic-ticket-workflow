"""Temporal activities: thin wrappers around the plain-Python core, with injected dependencies."""

import asyncio
import logging

from temporalio import activity

from agentic_ticket_workflow import agent
from agentic_ticket_workflow.agent import ChatModel
from agentic_ticket_workflow.helpdesk import FakeHelpdesk
from agentic_ticket_workflow.models import ActionResult, ActRequest, DecideResult, Ticket

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
        result = await asyncio.to_thread(agent.decide, ticket, self.model)
        log.info("model decided", extra={"tools": [call.name for call in result.tool_calls]})
        return result

    @activity.defn(name="act")
    async def act(self, req: ActRequest) -> ActionResult:
        result = self.helpdesk.perform(req)
        log.info("helpdesk action done", extra={"action": result.action.type, "helpdesk_ref": result.helpdesk_ref})
        return result
