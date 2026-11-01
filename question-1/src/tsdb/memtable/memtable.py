"""Memtable (implements ports.MemtablePort) = an OrderedStore of point versions + range tombstones.

It depends on the OrderedStore PORT, not on SkipList: bootstrap decides the structure.
Lifecycle: ACTIVE (takes writes) -> IMMUTABLE (frozen, being flushed, still readable) -> dropped
after its SSTable is in the MANIFEST.
Snapshot rule: a query with snapshot seq S sees only entries with seq <= S (no torn reads).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

from tsdb.model import Point, Seq, SeriesId, Timestamp, Tombstone
from tsdb.ports import OrderedStore


class Memtable:
    def __init__(self, store: OrderedStore, max_bytes: int) -> None:
        self._store = store
        self._max_bytes = max_bytes
        self._tombstones: dict[SeriesId, list[Tombstone]] = {}   # per-series lookup
        self._write_lock = threading.Lock()                      # one writer at a time
        self._approx_bytes = 0
        self._frozen = False
        self.max_seq: Seq = 0

    def apply(self, entries: list[Point | Tombstone]) -> None:
        raise NotImplementedError

    def freeze(self) -> None:
        raise NotImplementedError

    def is_full(self) -> bool:
        raise NotImplementedError

    def read_series(self, series_id: SeriesId, from_ts: Timestamp, to_ts: Timestamp,
                    snapshot_seq: Seq) -> Iterator[Point]:
        raise NotImplementedError

    def tombstones_for(self, series_id: SeriesId, snapshot_seq: Seq) -> list[Tombstone]:
        raise NotImplementedError

    def iter_for_flush(self) -> Iterator[Point]:
        """Newest version per (series, timestamp) only -> 'last write wins' happens here."""
        raise NotImplementedError

    def all_tombstones(self) -> list[Tombstone]:
        raise NotImplementedError
