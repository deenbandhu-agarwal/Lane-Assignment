"""Run limits and cost accounting."""

from __future__ import annotations

from dataclasses import dataclass

from agent.models.pricing import Price
from agent.types import Usage


@dataclass(frozen=True)
class Limits:
    max_steps: int = 10  # model calls per run
    max_cost_usd: float = 5.0
    step_timeout_s: float = 60.0  # per model call and per tool call
    max_repeat_calls: int = 3  # same tool + same args this many times -> loop
    max_malformed_steps: int = 3  # consecutive steps whose tool calls were all malformed


class Budget:
    """Tracks spend for one run.

    The cap is checked *before* each model call using the previous call's cost as
    the estimate for the next one, so a run stops before it would cross the cap
    rather than one call after.
    """

    def __init__(self, limits: Limits, price: Price) -> None:
        self.limits = limits
        self.price = price
        self.spent_usd = 0.0
        self.last_call_usd = 0.0

    def charge(self, usage: Usage) -> float:
        cost = self.price.cost(usage)
        self.spent_usd += cost
        self.last_call_usd = cost
        return cost

    def can_afford_next_call(self) -> bool:
        return self.spent_usd + self.last_call_usd < self.limits.max_cost_usd
