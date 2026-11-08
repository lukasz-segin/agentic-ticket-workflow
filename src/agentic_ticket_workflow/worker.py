"""Worker process, started by compose as `python -m agentic_ticket_workflow.worker`."""

import asyncio
import logging

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from agentic_ticket_workflow.activities import TicketActivities, check
from agentic_ticket_workflow.agent import ChatModel
from agentic_ticket_workflow.config import LlmSettings, Settings
from agentic_ticket_workflow.fake_llm import FakeChatModel
from agentic_ticket_workflow.helpdesk import FakeHelpdesk
from agentic_ticket_workflow.logs import configure_logging
from agentic_ticket_workflow.openai_llm import OpenAIChatModel
from agentic_ticket_workflow.workflow import TicketWorkflow


def build_model(llm: LlmSettings) -> ChatModel:
    if llm.mode == "openai":
        return OpenAIChatModel(llm.base_url, llm.model, llm.api_key)
    return FakeChatModel()


async def main() -> None:
    settings = Settings.from_env()
    # Before connecting: bad LLM config stops the worker before it takes any ticket.
    llm = LlmSettings.from_env()
    configure_logging(settings.log_level)
    # A failed connection raises and exits non-zero; compose's restart policy retries.
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        data_converter=pydantic_data_converter,
    )
    acts = TicketActivities(build_model(llm), FakeHelpdesk(settings.helpdesk_failure_rate))
    worker = Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[TicketWorkflow],
        activities=[acts.decide, check, acts.act],
    )
    # Names the mode only, never the key or the endpoint.
    logging.getLogger("agentic_ticket_workflow.worker").info(
        "worker started on task queue %s, LLM mode %s", settings.task_queue, llm.mode
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
