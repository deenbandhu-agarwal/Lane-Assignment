"""Streaming bucket aggregation. Buckets aligned to the epoch: start = ts - (ts mod size).
Memory = number of buckets, not points. Empty buckets are not returned.

OCP: each function is an Aggregator class; the registry maps the API name to its factory.
Adding p99 or last = one class + one registry entry; no other code changes.
"""

from __future__ import annotations

import re

from collections.abc import Iterator, Mapping

from tsdb.errors import ValidationError
from tsdb.model import Aggregation, Point
from tsdb.ports import AggregatorFactory


class Avg:
    def __init__(self) -> None:
        self._sum = 0.0
        self._count = 0

    def add(self, value: float) -> None:
        self._sum += value
        self._count += 1

    def result(self) -> float:
        return self._sum / self._count


class Sum:
    def __init__(self) -> None:
        self._sum = 0.0

    def add(self, value: float) -> None:
        self._sum += value

    def result(self) -> float:
        return self._sum


class Min:
    def __init__(self) -> None:
        self._min: float | None = None

    def add(self, value: float) -> None:
        self._min = value if self._min is None else min(self._min, value)

    def result(self) -> float:
        return self._min


class Max:
    def __init__(self) -> None:
        self._max: float | None = None

    def add(self, value: float) -> None:
        self._max = value if self._max is None else max(self._max, value)

    def result(self) -> float:
        return self._max


class Count:
    def __init__(self) -> None:
        self._count = 0

    def add(self, value: float) -> None:
        self._count += 1

    def result(self) -> float:
        return float(self._count)


AGGREGATORS: Mapping[Aggregation, AggregatorFactory] = {
    Aggregation.AVG: Avg,
    Aggregation.SUM: Sum,
    Aggregation.MIN: Min,
    Aggregation.MAX: Max,
    Aggregation.COUNT: Count,
}


_BUCKET = re.compile(r"([0-9]+)(ms|s|m|h|d)")
_UNIT_MS = {"ms": 1, "s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}


def parse_bucket(text: str) -> int:
    """'500ms' | '10s' | '1m' | '5m' | '1h' | '1d' -> milliseconds. Raises ValidationError."""
    match = _BUCKET.fullmatch(text)
    if not match or int(match[1]) == 0:
        raise ValidationError(f"bad bucket {text!r}: use a positive whole number + ms|s|m|h|d, e.g. '5m'")
    return int(match[1]) * _UNIT_MS[match[2]]


def bucket_start(timestamp: int, bucket_ms: int) -> int:
    return timestamp - timestamp % bucket_ms


class BucketAggregator:
    """Streams points into per-bucket Aggregators created from the injected factory."""

    def __init__(self, new_aggregator: AggregatorFactory, bucket_ms: int | None, from_ts: int) -> None:
        self._new_aggregator = new_aggregator
        self._bucket_ms = bucket_ms
        self._from_ts = from_ts

    def run(self, points: Iterator[Point]) -> list[tuple[int, float]]:
        """bucket_ms None -> one bucket for the whole range, keyed by from_ts.
        Points arrive in time order, so only the current bucket is open at any moment."""
        out: list[tuple[int, float]] = []
        current_start, current = None, None
        for p in points:
            start = self._from_ts if self._bucket_ms is None else bucket_start(p.timestamp, self._bucket_ms)
            if start != current_start:
                if current is not None:
                    out.append((current_start, current.result()))
                current_start, current = start, self._new_aggregator()
            current.add(p.value)
        if current is not None:
            out.append((current_start, current.result()))
        return out
