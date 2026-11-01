"""Flush: immutable memtable -> one new table PER TIME WINDOW it touches. Depends only on ports.

Rule: every table sits inside exactly one window. Points go to windows of the SMALLEST step
(config.window_steps_ms[0]); a memtable crossing a window edge, or holding late points, therefore
produces 2+ tables. A delete piece for an older, bigger window (e.g. a 1-day file) becomes a
delete-only table in that bigger window; compaction merges it like a late file.

Order (each step is safe to crash after; README crash table):
    1. swap, under swap_lock.exclusive() (design-qa #45, D2): freeze active memtable, new memtable
       from factory, wal.rotate_all(), install Version(new active, frozen as immutable)
                                                                                 -> hit(MEMTABLE_FLUSH)
    2. walk the memtable once (newest version per key); route each point to the writer of its
       window (writers opened lazily); cut each tombstone into the windows that may hold older
       data: this flush's windows + live tables' windows (split_by_window, design-qa #44)    -> hit(SSTABLE_WRITE)
    3. tables.publish each .tmp (rename + dir fsync)
    4. manifest.commit: add the new tables under their windows, raise last_flushed_seq and
       newest_data_ts                                                            -> hit(MANIFEST_UPDATE)
    5. versions.install(new Version); delete the old WAL segments
"""

from __future__ import annotations

import threading
from collections.abc import Iterable

from tsdb.engine.swap_lock import SwapLock
from tsdb.engine.version import VersionSet
from tsdb.model import Point, TimeWindow, Tombstone
from tsdb.ports import FaultInjector, FileOps, ManifestPort, MemtableFactory, MemtablePort, TableFactory, WalPort


def split_by_window(points: list[Point], tombstones: list[Tombstone], window_ms: int,
                    live_windows: Iterable[TimeWindow]) -> dict[TimeWindow, tuple[list[Point], list[Tombstone]]]:
    """Pure: group points by their smallest window; cut each tombstone ONLY into windows that may
    hold data older than it (design-qa #44):
        - the smallest windows of this flush's points
        - the windows of live tables (at their own size: one piece for a 1-day file, not 24)
    Older data can be nowhere else: memtables flush in order, so every earlier memtable is already
    a live table. An all-time delete (0 .. i64 max) therefore makes a few pieces, not one per window.
    Order inside each group stays (series_id, timestamp). Windows come out in time order."""
    groups: dict[TimeWindow, tuple[list[Point], list[Tombstone]]] = {}
    for p in points:
        groups.setdefault(TimeWindow.containing(p.timestamp, window_ms), ([], []))[0].append(p)
    data_windows = set(groups) | set(live_windows)
    for t in tombstones:
        for window in data_windows:
            piece = t.clip(window)
            if piece is not None:
                groups.setdefault(window, ([], []))[1].append(piece)
    return dict(sorted(groups.items(), key=lambda item: (item[0].start_ms, item[0].size_ms)))


class Flusher:
    def __init__(self, versions: VersionSet, wal: WalPort, manifest: ManifestPort, tables: TableFactory,
                 new_memtable: MemtableFactory, files: FileOps, faults: FaultInjector,
                 swap_lock: SwapLock, smallest_window_ms: int) -> None:
        self._swap_lock = swap_lock
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
