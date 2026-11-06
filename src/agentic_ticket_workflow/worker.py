"""Worker process, started by compose as `python -m agentic_ticket_workflow.worker`."""

import asyncio
import logging

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from agentic_ticket_workflow.activities import TicketActivities
from agentic_ticket_workflow.config import Settings
from agentic_ticket_workflow.fake_llm import FakeChatModel
from agentic_ticket_workflow.helpdesk import FakeHelpdesk
from agentic_ticket_workflow.workflow import TicketWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    # A failed connection raises and exits non-zero; compose's restart policy retries.
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        data_converter=pydantic_data_converter,
    )
    acts = TicketActivities(FakeChatModel(), FakeHelpdesk(settings.helpdesk_failure_rate))
    worker = Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[TicketWorkflow],
        activities=[acts.decide, acts.act],
    )
    logging.getLogger(__name__).info("worker started on task queue %s", settings.task_queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
