"""Seeded load generator: 10M points across 10K series (or --points/--series).

Deterministic for a given --seed: same series keys, same timestamps, same values, same order.
"""

from __future__ import annotations


def generate(points: int, series: int, seed: int):
    """Yield (SeriesKey, timestamp_ms, value) batches."""
    raise NotImplementedError
