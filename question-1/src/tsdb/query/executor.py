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
from tsdb.errors import QueryLimitError
from tsdb.model import Aggregation, SeriesId, SeriesKey, Timestamp
from tsdb.ports import AggregatorFactory, SeriesResolver
from tsdb.query.aggregate import BucketAggregator
from tsdb.query.merge import merge_series


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
        self._check_series_limit(series_ids)
        version, seq = self._snapshot.version, self._snapshot.seq
        self._points_read = 0
        memtables = (version.active, *version.immutables)
        tables = version.tables_overlapping(from_ts, to_ts)
        all_tables = sum(len(ts) for _, ts in version.windows)
        filter_skips = 0
        cursors = [(t, t.cursor()) for t in tables]            # one forward-only cursor per table
        result = QueryResult(series=[], agg=agg, bucket_ms=bucket_ms)
        for series_id in series_ids:                           # ascending: cursors only move forward
            tombstones = [t for m in memtables for t in m.tombstones_for(series_id, seq)]
            tombstones += [t for table in tables for t in table.tombstones_for(series_id)]
            sources = [m.read_series(series_id, from_ts, to_ts, seq) for m in memtables]
            for table, cursor in cursors:
                if table.may_contain(series_id, from_ts, to_ts):
                    sources.append(cursor.read_series(series_id, from_ts, to_ts))
                else:
                    filter_skips += 1
            points = self._count(merge_series(sources, tombstones))
            if agg is None:
                values = [(p.timestamp, p.value) for p in points]
            else:
                values = BucketAggregator(self._aggregators[agg], bucket_ms, from_ts).run(points)
            if values:
                result.series.append(SeriesResult(self._series.key_of(series_id), values))
        result.stats = {"tables_in_range": len(tables), "tables_skipped_by_time": all_tables - len(tables),
                        "tables_skipped_by_filter": filter_skips,
                        "blocks_read": sum(c.blocks_read for _, c in cursors)}
        return result

    def _count(self, points):
        """Counts points READ (also when aggregated): the limit bounds work, not answer size."""
        for p in points:
            self._points_read += 1
            if self._points_read > self._max_points:
                raise QueryLimitError(f"query reads more than {self._max_points} points; "
                                      "narrow the time range or the filter")
            yield p

    def list_series(self, series_ids: list[SeriesId]) -> SeriesListResult:
        """Catalog only: a series exists even when every point of it is deleted (design-qa #41)."""
        self._check_series_limit(series_ids)
        return SeriesListResult([self._series.key_of(i) for i in series_ids])

    def _check_series_limit(self, series_ids: list[SeriesId]) -> None:
        if len(series_ids) > self._max_series:
            raise QueryLimitError(f"query matches {len(series_ids)} series, limit is {self._max_series}; "
                                  "narrow the filter")
