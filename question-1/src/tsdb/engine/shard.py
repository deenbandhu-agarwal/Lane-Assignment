"""Shard = one complete LSM instance. A thin coordinator: it receives every collaborator through
its constructor (built by tsdb.bootstrap) and depends on ports, not concrete classes.

    write  : series.get_or_create -> wal.write (group commit, fsync) -> 200
    delete : filter -> fixed series ids -> wal.delete (range tombstone)
    read   : filter -> ids; versions.acquire(seq.visible) -> QueryExecutor -> release (never seq.last: #45)
    write  waits in background.wait_for_room() first (backpressure, #45)
Today the Database has exactly one shard; the class boundary is where multi-node sharding plugs in.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from tsdb.engine.background import BackgroundWorker
from tsdb.engine.seq import SequenceCounter
from tsdb.engine.version import Snapshot, VersionSet
from tsdb.model import Aggregation, SeriesKey, Timestamp
from tsdb.ports import PostingSource, SeriesResolver, WalPort
from tsdb.query.executor import QueryExecutor, QueryResult, SeriesListResult
from tsdb.query.filter import FilterExpr, evaluate

ExecutorFactory = Callable[[Snapshot], QueryExecutor]


class Shard:
    def __init__(self, series: SeriesResolver, index: PostingSource, wal: WalPort, versions: VersionSet,
                 seq: SequenceCounter, background: BackgroundWorker, new_executor: ExecutorFactory) -> None:
        self._series = series
        self._index = index
        self._wal = wal
        self._versions = versions
        self._seq = seq
        self._background = background
        self._new_executor = new_executor

    # ---- write path ---------------------------------------------------------------
    def write(self, points: Iterable[tuple[SeriesKey, Timestamp, float]]) -> int:
        """Already validated. Resolve/create series ids, hand to the WAL, block until durable."""
        self._background.wait_for_room()
        puts = [(key, self._series.get_or_create(key)[0], ts, value) for key, ts, value in points]
        self._wal.write(puts)
        self._background.wake()
        return len(puts)

    def delete(self, metric: str | None, expr: FilterExpr | None, from_ts: Timestamp, to_ts: Timestamp) -> int:
        """Resolve the series set NOW (fixed ids), write one range tombstone. Returns series count."""
        ids = evaluate(expr, self._index, metric)
        if ids:
            self._background.wait_for_room()
            self._wal.delete([(self._series.key_of(i), i) for i in ids], from_ts, to_ts)
            self._background.wake()
        return len(ids)

    # ---- read path ----------------------------------------------------------------
    def query(self, metric: str, expr: FilterExpr | None, from_ts: Timestamp, to_ts: Timestamp,
              agg: Aggregation | None, bucket_ms: int | None) -> QueryResult:
        ids = evaluate(expr, self._index, metric)
        snapshot = self._versions.acquire(self._seq.visible)      # never seq.last (#45)
        try:
            return self._new_executor(snapshot).run(ids, from_ts, to_ts, agg, bucket_ms)
        finally:
            self._versions.release(snapshot)

    def list_series(self, metric: str | None, expr: FilterExpr | None) -> SeriesListResult:
        snapshot = self._versions.acquire(self._seq.visible)
        try:
            return self._new_executor(snapshot).list_series(evaluate(expr, self._index, metric))
        finally:
            self._versions.release(snapshot)

    # ---- maintenance --------------------------------------------------------------
    def run_maintenance_until_idle(self) -> None:
        self._background.run_until_idle()

    def close(self) -> None:
        """Background first (a flush may still rotate WAL segments), then the WAL writers."""
        self._background.stop()
        self._wal.close()
        for _, tables in self._versions.current().windows:
            for table in tables:
                table.close()
