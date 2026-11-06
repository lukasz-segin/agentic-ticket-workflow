import pytest
from pydantic import ValidationError

from agentic_ticket_workflow.models import Ticket


def _ticket(**overrides) -> dict:
    return {"ticket_id": "T-1", "customer_id": "C-100", "subject": "Login", "body": "I forgot my password."} | overrides


def test_oversized_body_is_rejected():
    with pytest.raises(ValidationError):
        Ticket.model_validate(_ticket(body="x" * 10_001))


def test_oversized_subject_is_rejected():
    with pytest.raises(ValidationError):
        Ticket.model_validate(_ticket(subject="x" * 201))


def test_customer_id_must_be_a_plain_identifier():
    with pytest.raises(ValidationError):
        Ticket.model_validate(_ticket(customer_id="C-100 / drop"))
