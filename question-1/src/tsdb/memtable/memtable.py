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
        self._entries = 0                                        # points + tombstones
        self._frozen = False
        self.max_seq: Seq = 0
        self.max_timestamp: Timestamp = 0     # newest data time seen

    def apply(self, entries: list[Point | Tombstone]) -> None:
        """Entries arrive in seq order (one WAL batch). max_timestamp follows POINTS only: a delete
        reaching into the future must not close windows early."""
        with self._write_lock:
            if self._frozen:
                raise RuntimeError("memtable is frozen; writes go to the new active memtable")
            for e in entries:
                if isinstance(e, Tombstone):
                    for series_id in e.series_ids:
                        self._tombstones.setdefault(series_id, []).append(e)
                else:
                    self._store.insert((e.series_id, e.timestamp, -e.seq), e.value)
                    self.max_timestamp = max(self.max_timestamp, e.timestamp)
                self.max_seq = max(self.max_seq, e.seq)
            self._entries += len(entries)

    def freeze(self) -> None:
        with self._write_lock:
            self._frozen = True

    def is_full(self) -> bool:
        """Size estimate (entries x entry_bytes) or the hard entry cap, whichever comes first."""
        return self._entries * self._entry_bytes >= self._max_bytes or self._entries >= self._max_entries

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
        last = None
        for (sid, ts, neg_seq), value in self._store:
            if (sid, ts) != last:              # versions are newest first, so the first one wins
                last = (sid, ts)
                yield Point(sid, ts, -neg_seq, value)

    def all_tombstones(self) -> list[Tombstone]:
        """Each tombstone once (one covering several series sits in several per-series lists)."""
        return sorted({t for ts in self._tombstones.values() for t in ts}, key=lambda t: t.seq)
