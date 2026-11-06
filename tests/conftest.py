import pytest

from agentic_ticket_workflow.models import Ticket
from agentic_ticket_workflow.tools import load_data


@pytest.fixture
def tickets() -> dict[str, Ticket]:
    """The example tickets T-1…T-7, keyed by ticket ID."""
    return {t["ticket_id"]: Ticket.model_validate(t) for t in load_data("tickets")}
