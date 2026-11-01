"""Consistent snapshots for readers while writes, flushes and compactions run.

A Version is an immutable picture: (active memtable, immutable memtables, tables per time window,
newest data time).
Flush and compaction never change a Version; they build a new one and `install` it.

    snap = versions.acquire(seq)   # Version + snapshot seq, refcount +1
    ... read memtables (seq <= snap.seq) and snap's tables ...
    versions.release(snap)         # refcount -1

A table file is closed and deleted only when no live Version references it, so compaction can never
delete a file under a running query. With the seq filter on memtables, every query sees one
consistent snapshot (no torn reads). Depends only on ports.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from tsdb.model import Seq, TimeWindow, Timestamp
from tsdb.ports import MemtablePort, TableReader


@dataclass(frozen=True, slots=True)
class Version:
    number: int
    active: MemtablePort
    immutables: tuple[MemtablePort, ...]                 # newest first, being flushed
    windows: tuple[tuple[TimeWindow, tuple[TableReader, ...]], ...]   # sorted by start; files newest first
    newest_data_ts: Timestamp                            # max(flushed, memtables): drives window closing

    def tables_overlapping(self, from_ts: Timestamp, to_ts: Timestamp) -> list[TableReader]:
        """Tables whose window overlaps [from, to]: the first, cheapest pruning step of a read."""
        raise NotImplementedError

    def tables_in(self, window: TimeWindow) -> tuple[TableReader, ...]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class Snapshot:
    version: Version
    seq: Seq


OnObsolete = Callable[[TableReader], None]   # close + delete a table nobody uses any more


class VersionSet:
    def __init__(self, initial: Version, on_obsolete: OnObsolete) -> None:
        self._current = initial
        self._on_obsolete = on_obsolete
        self._refs: dict[int, int] = {}                  # version number -> running snapshots
        self._live: dict[int, Version] = {initial.number: initial}   # current + versions in use
        self._lock = threading.Lock()

    def acquire(self, seq: Seq) -> Snapshot:
        with self._lock:
            version = self._current
            self._refs[version.number] = self._refs.get(version.number, 0) + 1
            return Snapshot(version, seq)

    def release(self, snapshot: Snapshot) -> None:
        number = snapshot.version.number
        with self._lock:
            self._refs[number] -= 1
            if self._refs[number] > 0:
                return
            del self._refs[number]
            obsolete = self._drop(number)
        self._delete(obsolete)

    def current(self) -> Version:
        with self._lock:
            return self._current

    def install(self, new: Version) -> None:
        """Called AFTER the MANIFEST commit that made `new` durable."""
        with self._lock:
            old = self._current
            self._current = new
            self._live[new.number] = new
            obsolete = self._drop(old.number) if old.number not in self._refs else []
        self._delete(obsolete)

    def _drop(self, number: int) -> list[TableReader]:
        """Forget a version nobody uses; return its tables that no live version still has.
        Caller holds the lock."""
        if number == self._current.number:
            return []
        gone = self._live.pop(number)
        still_used = {t.name for v in self._live.values() for _, tables in v.windows for t in tables}
        return [t for _, tables in gone.windows for t in tables if t.name not in still_used]

    def _delete(self, tables: list[TableReader]) -> None:
        for table in tables:                 # outside the lock: closing/deleting files is slow
            self._on_obsolete(table)
