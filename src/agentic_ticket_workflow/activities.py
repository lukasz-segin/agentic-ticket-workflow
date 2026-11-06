"""Temporal activities: thin wrappers around the plain-Python core, with injected dependencies."""

import asyncio

from temporalio import activity

from agentic_ticket_workflow import agent
from agentic_ticket_workflow.agent import ChatModel
from agentic_ticket_workflow.helpdesk import FakeHelpdesk
from agentic_ticket_workflow.models import ActionResult, ActRequest, DecideResult, Ticket


class TicketActivities:
    def __init__(self, model: ChatModel, helpdesk: FakeHelpdesk) -> None:
        self.model = model
        self.helpdesk = helpdesk

    @activity.defn(name="decide")
    async def decide(self, ticket: Ticket) -> DecideResult:
        # The model call may block (a real provider in S-08), so keep it off the event loop.
        return await asyncio.to_thread(agent.decide, ticket, self.model)

    @activity.defn(name="act")
    async def act(self, req: ActRequest) -> ActionResult:
        return self.helpdesk.perform(req)
