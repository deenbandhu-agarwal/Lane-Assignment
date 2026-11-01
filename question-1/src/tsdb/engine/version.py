"""Consistent snapshots for readers while writes, flushes and compactions run.

A Version is an immutable picture: (active memtable, immutable memtables, tables per level).
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

from tsdb.model import Seq
from tsdb.ports import MemtablePort, TableReader


@dataclass(frozen=True, slots=True)
class Version:
    number: int
    active: MemtablePort
    immutables: tuple[MemtablePort, ...]                 # newest first, being flushed
    levels: tuple[tuple[TableReader, ...], ...]          # levels[0] = L0 newest first


@dataclass(frozen=True, slots=True)
class Snapshot:
    version: Version
    seq: Seq


OnObsolete = Callable[[TableReader], None]   # close + delete a table nobody uses any more


class VersionSet:
    def __init__(self, initial: Version, on_obsolete: OnObsolete) -> None:
        self._current = initial
        self._on_obsolete = on_obsolete
        self._refs: dict[int, int] = {}
        self._lock = threading.Lock()

    def acquire(self, seq: Seq) -> Snapshot:
        raise NotImplementedError

    def release(self, snapshot: Snapshot) -> None:
        raise NotImplementedError

    def current(self) -> Version:
        raise NotImplementedError

    def install(self, new: Version) -> None:
        """Called AFTER the MANIFEST commit that made `new` durable."""
        raise NotImplementedError
