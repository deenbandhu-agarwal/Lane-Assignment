"""Database (implements ports.TimeSeriesStore): what the API talks to. Routes writes to shards via
the injected ShardRouter; reads fan out to every shard and merge. Built by tsdb.bootstrap."""

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
        raise NotImplementedError

    def query(self, metric: str, filter_text: str | None, from_ts: Timestamp, to_ts: Timestamp,
              agg: Aggregation | None, bucket_ms: int | None) -> QueryResult:
        raise NotImplementedError

    def list_series(self, metric: str | None, filter_text: str | None) -> SeriesListResult:
        raise NotImplementedError

    def delete(self, metric: str | None, filter_text: str | None, from_ts: Timestamp, to_ts: Timestamp) -> int:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
