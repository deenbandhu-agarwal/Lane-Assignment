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
    4+5. LiveState.commit(Edit): MANIFEST gets the new tables under their windows, last_flushed_seq,
       newest_data_ts and the next WAL segment            -> hit(MANIFEST_UPDATE) inside the commit;
       then the new Version (files in, frozen memtable out) is installed; then the old WAL
       segments are deleted
"""

from __future__ import annotations

import threading
from pathlib import Path
from collections.abc import Iterable

from tsdb.engine.state import Edit, LiveState
from tsdb.engine.swap_lock import SwapLock
from tsdb.engine.version import VersionSet
from tsdb.model import Point, TimeWindow, Tombstone
from tsdb.faults import CrashPoint
from tsdb.ports import FaultInjector, FileOps, MemtableFactory, MemtablePort, TableFactory, WalPort


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
    def __init__(self, versions: VersionSet, wal: WalPort, state: LiveState, tables: TableFactory,
                 new_memtable: MemtableFactory, files: FileOps, faults: FaultInjector,
                 swap_lock: SwapLock, smallest_window_ms: int) -> None:
        self._versions = versions
        self._wal = wal
        self._state = state
        self._tables = tables
        self._new_memtable = new_memtable
        self._files = files
        self._faults = faults
        self._swap_lock = swap_lock
        self._smallest_window_ms = smallest_window_ms
        self._lock = threading.Lock()      # one flush at a time; memtables flush in order
        self._segments: dict[int, tuple[int, list[Path]]] = {}   # id(memtable) -> (its segment, files)

    def swap_memtable(self) -> MemtablePort:
        """Step 1. Returns the frozen memtable (now immutable, still readable)."""
        with self._swap_lock.exclusive():
            current = self._versions.current()
            frozen = current.active
            frozen.freeze()
            active = self._new_memtable()
            segment = self._state.next_segment()
            old_files = self._wal.rotate_all(segment, active)
            self._segments[id(frozen)] = (segment - 1, old_files)
            self._state.install_memtables(active, (frozen, *current.immutables))
        self._faults.hit(CrashPoint.MEMTABLE_FLUSH)
        return frozen

    def flush(self, memtable: MemtablePort) -> None:
        """Steps 2-5."""
        with self._lock:
            live_windows = [w for w, _ in self._versions.current().windows]
            groups = split_by_window(list(memtable.iter_for_flush()), memtable.all_tombstones(),
                                     self._smallest_window_ms, live_windows)
            added = []
            for window, (points, tombstones) in groups.items():
                file_no = self._state.allocate_file_no()
                writer = self._tables.new_writer(window, file_no)
                for t in tombstones:
                    writer.add_tombstone(t)
                for p in points:
                    writer.add(p)
                final = self._tables.publish(writer.finish(), window, file_no)
                added.append((window, self._tables.open_reader(final, window)))
            segment, old_files = self._segments.pop(id(memtable))
            self._state.commit(Edit(added=tuple(added), flushed=memtable, wal_segment=segment + 1))
            for path in old_files:
                self._files.remove(path)
