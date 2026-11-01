"""Streaming bucket aggregation. Buckets aligned to the epoch: start = ts - (ts mod size).
Memory = number of buckets, not points. Empty buckets are not returned.

OCP: each function is an Aggregator class; the registry maps the API name to its factory.
Adding p99 or last = one class + one registry entry; no other code changes.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from tsdb.model import Aggregation, Point
from tsdb.ports import AggregatorFactory


class Avg:
    def __init__(self) -> None:
        self._sum = 0.0
        self._count = 0

    def add(self, value: float) -> None:
        raise NotImplementedError

    def result(self) -> float:
        raise NotImplementedError


class Sum:
    def __init__(self) -> None:
        self._sum = 0.0

    def add(self, value: float) -> None:
        raise NotImplementedError

    def result(self) -> float:
        raise NotImplementedError


class Min:
    def __init__(self) -> None:
        self._min: float | None = None

    def add(self, value: float) -> None:
        raise NotImplementedError

    def result(self) -> float:
        raise NotImplementedError


class Max:
    def __init__(self) -> None:
        self._max: float | None = None

    def add(self, value: float) -> None:
        raise NotImplementedError

    def result(self) -> float:
        raise NotImplementedError


class Count:
    def __init__(self) -> None:
        self._count = 0

    def add(self, value: float) -> None:
        raise NotImplementedError

    def result(self) -> float:
        raise NotImplementedError


AGGREGATORS: Mapping[Aggregation, AggregatorFactory] = {
    Aggregation.AVG: Avg,
    Aggregation.SUM: Sum,
    Aggregation.MIN: Min,
    Aggregation.MAX: Max,
    Aggregation.COUNT: Count,
}


def parse_bucket(text: str) -> int:
    """'500ms' | '10s' | '1m' | '5m' | '1h' | '1d' -> milliseconds. Raises ValidationError."""
    raise NotImplementedError


def bucket_start(timestamp: int, bucket_ms: int) -> int:
    raise NotImplementedError


class BucketAggregator:
    """Streams points into per-bucket Aggregators created from the injected factory."""

    def __init__(self, new_aggregator: AggregatorFactory, bucket_ms: int | None, from_ts: int) -> None:
        self._new_aggregator = new_aggregator
        self._bucket_ms = bucket_ms
        self._from_ts = from_ts

    def run(self, points: Iterator[Point]) -> list[tuple[int, float]]:
        """bucket_ms None -> one bucket for the whole range, keyed by from_ts."""
        raise NotImplementedError
