"""Runs /query and /series against ONE snapshot. Depends only on ports + pure query functions.

Read plan (README "Read path"):
    1. series ids (sorted) come from the caller (filter.evaluate on the PostingSource)   memory
    2. limits check (series count)                                                       memory
    3. one TableCursor per table (forward only; neighbour series reuse a block)
    4. per series, in id order:
         tombstones = memtables + every table's per-series map                           memory
         sources    = memtables + tables passing may_contain()                           memory
         points     = merge_series(sources, tombstones)                     disk: data blocks only
         result     = BucketAggregator(AGGREGATORS[agg]) or raw points                   memory
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from tsdb.engine.version import Snapshot
from tsdb.model import Aggregation, SeriesId, SeriesKey, Timestamp
from tsdb.ports import AggregatorFactory, SeriesResolver


@dataclass(slots=True)
class SeriesResult:
    key: SeriesKey
    points: list[tuple[int, float]] = field(default_factory=list)     # raw or bucketed


@dataclass(slots=True)
class QueryResult:
    series: list[SeriesResult]
    agg: Aggregation | None = None
    bucket_ms: int | None = None
    stats: dict[str, int] = field(default_factory=dict)   # blocks_read, tables_skipped, filter_skips


@dataclass(slots=True)
class SeriesListResult:
    series: list[SeriesKey]


class QueryExecutor:
    def __init__(self, snapshot: Snapshot, series: SeriesResolver,
                 aggregators: Mapping[Aggregation, AggregatorFactory],
                 max_series: int, max_points: int) -> None:
        self._snapshot = snapshot
        self._series = series
        self._aggregators = aggregators
        self._max_series = max_series
        self._max_points = max_points

    def run(self, series_ids: list[SeriesId], from_ts: Timestamp, to_ts: Timestamp,
            agg: Aggregation | None, bucket_ms: int | None) -> QueryResult:
        raise NotImplementedError

    def list_series(self, series_ids: list[SeriesId]) -> SeriesListResult:
        raise NotImplementedError
