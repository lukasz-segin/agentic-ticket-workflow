"""Test doubles shared by several test modules."""

import random

from agentic_ticket_workflow.helpdesk import FakeHelpdesk
from agentic_ticket_workflow.models import ActionResult, ActRequest


class ScriptedRandom(random.Random):
    """Returns the given values from random(), in order; raises StopIteration once they run out."""

    def __init__(self, values: list[float]):
        super().__init__()
        self.values = iter(values)

    def random(self) -> float:
        return next(self.values)


class _WriteCountingDict(dict):
    def __init__(self) -> None:
        super().__init__()
        self.writes = 0

    def __setitem__(self, key, value) -> None:
        self.writes += 1
        super().__setitem__(key, value)


class CountingHelpdesk(FakeHelpdesk):
    """Counts every call, and every action carried out: each write to `performed` is one execution.

    Counting writes, not keys, means a second execution under the same key, which would only overwrite the
    dict entry, still shows up."""

    def __init__(self, failure_rate: float, rng: random.Random | None = None) -> None:
        super().__init__(failure_rate, rng)
        self.performed = _WriteCountingDict()
        self.calls = 0

    @property
    def executions(self) -> int:
        return self.performed.writes

    def perform(self, req: ActRequest) -> ActionResult:
        self.calls += 1
        return super().perform(req)
