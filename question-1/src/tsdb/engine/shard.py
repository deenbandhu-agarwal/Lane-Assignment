"""Shard = one complete LSM instance. A thin coordinator: it receives every collaborator through
its constructor (built by tsdb.bootstrap) and depends on ports, not concrete classes.

    write  : series.get_or_create -> wal.write (group commit, fsync) -> 200
    delete : filter -> fixed series ids -> wal.delete (range tombstone)
    read   : versions.acquire(seq.last) -> QueryExecutor -> versions.release
Today the Database has exactly one shard; the class boundary is where multi-node sharding plugs in.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from tsdb.engine.background import BackgroundWorker
from tsdb.engine.seq import SequenceCounter
from tsdb.engine.version import Snapshot, VersionSet
from tsdb.model import SeriesKey, Timestamp
from tsdb.ports import PostingSource, SeriesResolver, WalPort
from tsdb.query.executor import QueryExecutor
from tsdb.query.filter import FilterExpr

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
        raise NotImplementedError

    def delete(self, metric: str | None, expr: FilterExpr | None, from_ts: Timestamp, to_ts: Timestamp) -> int:
        """Resolve the series set NOW (fixed ids), write one range tombstone. Returns series count."""
        raise NotImplementedError

    # ---- read path ----------------------------------------------------------------
    def executor(self) -> tuple[QueryExecutor, Snapshot]:
        """Caller must release the snapshot (use `with shard.reading() as ex:` helper later)."""
        raise NotImplementedError

    def release(self, snapshot: Snapshot) -> None:
        raise NotImplementedError

    @property
    def index(self) -> PostingSource:
        return self._index

    @property
    def series(self) -> SeriesResolver:
        return self._series

    # ---- maintenance --------------------------------------------------------------
    def run_maintenance_until_idle(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
