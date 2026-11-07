"""Test doubles shared by several test modules."""

import random


class ScriptedRandom(random.Random):
    """Returns the given values from random(), in order; raises StopIteration once they run out."""

    def __init__(self, values: list[float]):
        super().__init__()
        self.values = iter(values)

    def random(self) -> float:
        return next(self.values)
