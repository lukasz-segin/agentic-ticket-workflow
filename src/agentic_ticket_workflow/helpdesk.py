"""Fake Helpdesk API: fails at random, but never performs one idempotency key twice.

Keys live in memory, so they are lost when the worker restarts (a known limitation).
"""

import random

from agentic_ticket_workflow.models import ActionResult, ActRequest


class HelpdeskTemporaryError(Exception):
    """A temporary helpdesk failure; a retry may succeed."""


class FakeHelpdesk:
    def __init__(self, failure_rate: float, rng: random.Random | None = None) -> None:
        self.failure_rate = failure_rate
        self.rng = rng or random.Random()
        self.performed: dict[str, ActionResult] = {}

    def perform(self, req: ActRequest) -> ActionResult:
        fails = self.rng.random() < self.failure_rate
        known = self.performed.get(req.idempotency_key)
        if known is not None:
            # A repeat may also fail, but never performs the action again.
            if fails:
                raise HelpdeskTemporaryError("helpdesk unavailable (known key)")
            return known
        # A failure may hit before or after the action is recorded, so retries also meet a known key.
        if fails and self.rng.random() < 0.5:
            raise HelpdeskTemporaryError("helpdesk unavailable (before recording)")
        result = ActionResult(action=req.action, helpdesk_ref=f"HD-{len(self.performed) + 1}")
        self.performed[req.idempotency_key] = result
        if fails:
            raise HelpdeskTemporaryError("helpdesk unavailable (after recording)")
        return result
