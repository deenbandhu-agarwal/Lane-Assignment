"""Per-model prices, so the cost cap works the same for every provider.

Unknown models fail closed: without a price the cost cap could not be enforced.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.types import Usage


@dataclass(frozen=True)
class Price:
    input_per_mtok: float  # USD per 1M input tokens
    output_per_mtok: float  # USD per 1M output tokens

    def cost(self, usage: Usage) -> float:
        return (
            usage.input_tokens * self.input_per_mtok + usage.output_tokens * self.output_per_mtok
        ) / 1_000_000


PRICES: dict[str, Price] = {
    # Fake model: arbitrary but non-zero, so cost-cap tests exercise real arithmetic.
    "fake": Price(input_per_mtok=1.0, output_per_mtok=4.0),
    # gemini-3.5-flash is not on ai.google.dev/gemini-api/docs/pricing (checked 2026-11-01).
    # Priced at the listed Gemini 3.6/3.8 Flash standard paid rate, the highest Flash rate
    # listed, so the cost cap over- rather than under-estimates. Free tier actually costs $0.
    "gemini-3.5-flash": Price(input_per_mtok=0.75, output_per_mtok=3.75),
    "gemini-3.8-flash": Price(input_per_mtok=0.75, output_per_mtok=3.75),
}


def price_for(model_name: str) -> Price:
    try:
        return PRICES[model_name]
    except KeyError:
        raise ValueError(
            f"no price configured for model {model_name!r}; add it to agent.models.pricing.PRICES"
        ) from None
