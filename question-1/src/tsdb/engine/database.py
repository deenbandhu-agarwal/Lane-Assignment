"""Database (implements ports.TimeSeriesStore): what the API talks to. Routes writes to shards via
the injected ShardRouter; reads and deletes fan out to every shard (a filter can match series in
any shard) and the parts are concatenated. Built by tsdb.bootstrap."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from tsdb.engine.shard import Shard
from tsdb.model import Aggregation, SeriesKey, Timestamp
from tsdb.ports import ShardRouter
from tsdb.query.executor import QueryResult, SeriesListResult
from tsdb.query.filter import FilterExpr

FilterParser = Callable[[str], FilterExpr]


class Database:
    def __init__(self, shards: list[Shard], router: ShardRouter, parse_filter: FilterParser) -> None:
        self._shards = shards
        self._router = router
        self._parse_filter = parse_filter

    def write(self, points: Iterable[tuple[SeriesKey, Timestamp, float]]) -> int:
        per_shard: dict[int, list[tuple[SeriesKey, Timestamp, float]]] = {}
        for point in points:
            per_shard.setdefault(self._router.route(point[0]), []).append(point)
        return sum(self._shards[i].write(batch) for i, batch in per_shard.items())

    def query(self, metric: str, filter_text: str | None, from_ts: Timestamp, to_ts: Timestamp,
              agg: Aggregation | None, bucket_ms: int | None) -> QueryResult:
        expr = self._parse(filter_text)
        parts = [s.query(metric, expr, from_ts, to_ts, agg, bucket_ms) for s in self._shards]
        stats: dict[str, int] = {}
        for part in parts:
            for name, value in part.stats.items():
                stats[name] = stats.get(name, 0) + value
        return QueryResult([s for part in parts for s in part.series], agg, bucket_ms, stats)

    def list_series(self, metric: str | None, filter_text: str | None) -> SeriesListResult:
        expr = self._parse(filter_text)
        return SeriesListResult([k for s in self._shards for k in s.list_series(metric, expr).series])

    def delete(self, metric: str | None, filter_text: str | None, from_ts: Timestamp, to_ts: Timestamp) -> int:
        expr = self._parse(filter_text)
        return sum(s.delete(metric, expr, from_ts, to_ts) for s in self._shards)

    def run_maintenance_until_idle(self) -> None:
        """Tests / benchmarks: flush everything, compact until nothing is left."""
        for shard in self._shards:
            shard.run_maintenance_until_idle()

    def close(self) -> None:
        for shard in self._shards:
            shard.close()

    def _parse(self, filter_text: str | None) -> FilterExpr | None:
        return self._parse_filter(filter_text) if filter_text and filter_text.strip() else None
