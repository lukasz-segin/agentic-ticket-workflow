import random

import pytest

from agentic_ticket_workflow.helpdesk import FakeHelpdesk, HelpdeskTemporaryError
from agentic_ticket_workflow.models import ActRequest, ReplyAction


def _request(key: str = "ticket-T-1:reply") -> ActRequest:
    return ActRequest(ticket_id="T-1", idempotency_key=key, action=ReplyAction(message="hi", article_ids=["KB-1"]))


class ScriptedRandom(random.Random):
    """Returns the given values from random(), in order."""

    def __init__(self, values: list[float]):
        super().__init__()
        self.values = iter(values)

    def random(self) -> float:
        return next(self.values)


def test_same_key_is_performed_once():
    helpdesk = FakeHelpdesk(0.0)
    first = helpdesk.perform(_request())
    second = helpdesk.perform(_request())
    assert len(helpdesk.performed) == 1
    assert first.helpdesk_ref == second.helpdesk_ref


def test_full_failure_rate_raises():
    with pytest.raises(HelpdeskTemporaryError):
        FakeHelpdesk(1.0).perform(_request())


def test_failure_after_recording_then_retry_returns_recorded_result():
    # 1st call: fail roll (0.0 < rate), then "after recording" branch (0.9 >= 0.5).
    # Retry: roll passes (0.9 >= rate), the known key returns its recorded result.
    helpdesk = FakeHelpdesk(0.5, rng=ScriptedRandom([0.0, 0.9, 0.9]))
    with pytest.raises(HelpdeskTemporaryError):
        helpdesk.perform(_request())
    retried = helpdesk.perform(_request())  # known key: no new action
    assert len(helpdesk.performed) == 1
    assert retried.helpdesk_ref == "HD-1"


def test_known_key_can_still_fail_without_acting_again():
    helpdesk = FakeHelpdesk(0.0)
    helpdesk.perform(_request())
    helpdesk.failure_rate = 1.0
    with pytest.raises(HelpdeskTemporaryError):
        helpdesk.perform(_request())
    assert len(helpdesk.performed) == 1


def test_failure_before_recording_records_nothing():
    helpdesk = FakeHelpdesk(0.5, rng=ScriptedRandom([0.0, 0.1]))
    with pytest.raises(HelpdeskTemporaryError):
        helpdesk.perform(_request())
    assert helpdesk.performed == {}
