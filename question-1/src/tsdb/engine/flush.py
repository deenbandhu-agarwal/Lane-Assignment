"""Flush: immutable memtable -> one new table PER TIME WINDOW it touches. Depends only on ports.

Rule: every table sits inside exactly one window of the SMALLEST step (config.window_steps_ms[0]).
A memtable crossing a window edge, or holding late points, therefore produces 2+ tables.

Order (each step is safe to crash after; README crash table):
    1. swap: freeze active memtable, new memtable from factory, wal.rotate_all()  -> hit(MEMTABLE_FLUSH)
    2. walk the memtable once (newest version per key); route each point to the writer of its
       window (writers opened lazily); cut each tombstone with Tombstone.clip(window) into every
       window it covers                                                          -> hit(SSTABLE_WRITE)
    3. tables.publish each .tmp (rename + dir fsync)
    4. manifest.commit: add the new tables under their windows, raise last_flushed_seq and
       newest_data_ts                                                            -> hit(MANIFEST_UPDATE)
    5. versions.install(new Version); delete the old WAL segments
"""

from __future__ import annotations

import threading

from tsdb.engine.version import VersionSet
from tsdb.model import Point, TimeWindow, Tombstone
from tsdb.ports import FaultInjector, FileOps, ManifestPort, MemtableFactory, MemtablePort, TableFactory, WalPort


def split_by_window(points: list[Point], tombstones: list[Tombstone],
                    window_ms: int) -> dict[TimeWindow, tuple[list[Point], list[Tombstone]]]:
    """Pure: group points by their smallest window and clip tombstones into every window they cover.
    Order inside each group stays (series_id, timestamp)."""
    raise NotImplementedError


class Flusher:
    def __init__(self, versions: VersionSet, wal: WalPort, manifest: ManifestPort, tables: TableFactory,
                 new_memtable: MemtableFactory, files: FileOps, faults: FaultInjector,
                 smallest_window_ms: int) -> None:
        self._versions = versions
        self._wal = wal
        self._manifest = manifest
        self._tables = tables
        self._new_memtable = new_memtable
        self._files = files
        self._faults = faults
        self._smallest_window_ms = smallest_window_ms
        self._lock = threading.Lock()      # one flush at a time; memtables flush in order

    def swap_memtable(self) -> MemtablePort:
        """Step 1. Returns the frozen memtable (now immutable, still readable)."""
        raise NotImplementedError

    def flush(self, memtable: MemtablePort) -> None:
        """Steps 2-5."""
        raise NotImplementedError
