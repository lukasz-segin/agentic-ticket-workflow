import pytest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from agentic_ticket_workflow.models import Ticket
from agentic_ticket_workflow.tools import load_data


@pytest.fixture
def tickets() -> dict[str, Ticket]:
    """The example tickets T-1…T-7, keyed by ticket ID."""
    return {t["ticket_id"]: Ticket.model_validate(t) for t in load_data("tickets")}


@pytest.fixture
async def env():
    """A time-skipping Temporal test server with the pydantic converter, as the app uses."""
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        yield env
