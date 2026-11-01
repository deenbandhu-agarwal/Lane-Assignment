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


_NEWEST = -(2**63)        # smallest -seq: sorts before every version of a (series, ts)


class Memtable:
    def __init__(self, store: OrderedStore, max_bytes: int, entry_bytes: int, max_entries: int) -> None:
        self._store = store
        self._max_bytes = max_bytes
        self._entry_bytes = entry_bytes       # size estimate per entry (Python objects are not bytes)
        self._max_entries = max_entries
        self._tombstones: dict[SeriesId, list[Tombstone]] = {}   # per-series lookup
        self._write_lock = threading.Lock()                      # one writer at a time
        self._approx_bytes = 0
        self._frozen = False
        self.max_seq: Seq = 0
        self.max_timestamp: Timestamp = 0     # newest data time seen

    def apply(self, entries: list[Point | Tombstone]) -> None:
        with self._write_lock:
            for e in entries:
                if isinstance(e, Tombstone):
                    for series_id in e.series_ids:
                        self._tombstones.setdefault(series_id, []).append(e)
                else:
                    self._store.insert((e.series_id, e.timestamp, -e.seq), e.value)

    def freeze(self) -> None:
        raise NotImplementedError

    def is_full(self) -> bool:
        raise NotImplementedError

    def read_series(self, series_id: SeriesId, from_ts: Timestamp, to_ts: Timestamp,
                    snapshot_seq: Seq) -> Iterator[Point]:
        """Per timestamp, the newest version with seq <= snapshot_seq. Tombstones are NOT applied
        here: the query merge applies them once across memtables and files (Rule 1)."""
        last_ts = None
        for (sid, ts, neg_seq), value in self._store.iter_from((series_id, from_ts, _NEWEST)):
            if sid != series_id or ts > to_ts:
                return
            if ts == last_ts or -neg_seq > snapshot_seq:
                continue                      # an older version of a ts already returned / too new
            last_ts = ts
            yield Point(sid, ts, -neg_seq, value)

    def tombstones_for(self, series_id: SeriesId, snapshot_seq: Seq) -> list[Tombstone]:
        return [t for t in self._tombstones.get(series_id, ()) if t.seq <= snapshot_seq]

    def iter_for_flush(self) -> Iterator[Point]:
        """Newest version per (series, timestamp) only -> 'last write wins' happens here."""
        raise NotImplementedError

    def all_tombstones(self) -> list[Tombstone]:
        raise NotImplementedError
