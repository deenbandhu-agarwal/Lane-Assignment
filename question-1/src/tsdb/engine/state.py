"""LiveState: the ONE place that changes the MANIFEST and installs Versions (design-qa #47).

Flush and compaction run on two threads (#45 D3) and both do "read state -> change -> commit
MANIFEST -> install Version". Without one lock a compaction commit built from an older state could
overwrite a flush commit and a new file would vanish from the MANIFEST. Here every change is an
Edit applied under one lock, in this order:
    new state = old state + edit  ->  manifest.commit(new state)  ->  versions.install(new Version)
File numbers are handed out here too (two threads never get the same number). A number used by a
crashed run that never reached the MANIFEST is an orphan; recovery deletes it.
Depends only on ports.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace

from tsdb.engine.version import Version, VersionSet
from tsdb.model import ManifestState, TimeWindow
from tsdb.ports import ManifestPort, MemtablePort, TableReader


@dataclass(frozen=True, slots=True)
class Edit:
    added: tuple[tuple[TimeWindow, TableReader], ...] = ()
    removed: frozenset[str] = frozenset()             # table names
    flushed: MemtablePort | None = None               # leaves the Version's immutables
    wal_segment: int | None = None                    # oldest WAL segment still needed for replay


class LiveState:
    def __init__(self, manifest: ManifestPort, versions: VersionSet, state: ManifestState,
                 active_segment: int) -> None:
        self._manifest = manifest
        self._versions = versions
        self._state = state
        self._next_file_no = state.next_file_no
        self._active_segment = active_segment
        self._lock = threading.Lock()

    @property
    def state(self) -> ManifestState:
        with self._lock:
            return self._state

    def allocate_file_no(self) -> int:
        with self._lock:
            n = self._next_file_no
            self._next_file_no += 1
            return n

    def next_segment(self) -> int:
        """WAL segment number for the memtable that becomes active at a swap."""
        with self._lock:
            self._active_segment += 1
            return self._active_segment

    def install_memtables(self, active: MemtablePort, immutables: tuple[MemtablePort, ...]) -> None:
        """Memtable swap: no file changes, so no MANIFEST commit."""
        with self._lock:
            current = self._versions.current()
            self._versions.install(replace(current, number=current.number + 1, active=active,
                                           immutables=immutables))

    def commit(self, edit: Edit) -> None:
        with self._lock:
            current = self._versions.current()
            state = self._state
            windows = {w: list(names) for w, names in state.windows}
            readers = {w: list(tables) for w, tables in current.windows}
            for window in windows:
                windows[window] = [n for n in windows[window] if n not in edit.removed]
                readers[window] = [t for t in readers[window] if t.name not in edit.removed]
            for window, table in edit.added:
                windows.setdefault(window, []).append(table.name)            # oldest first on disk
                readers.setdefault(window, []).insert(0, table)              # newest first in memory
            order = sorted((w for w in windows if windows[w]), key=lambda w: (w.start_ms, w.size_ms))
            flushed = edit.flushed
            new_state = replace(
                state, version=state.version + 1, next_file_no=self._next_file_no,
                windows=tuple((w, tuple(windows[w])) for w in order),
                last_flushed_seq=max(state.last_flushed_seq, flushed.max_seq if flushed else 0),
                newest_data_ts=max(state.newest_data_ts, flushed.max_timestamp if flushed else 0),
                wal_segment=edit.wal_segment if edit.wal_segment is not None else state.wal_segment)
            self._manifest.commit(new_state)                 # the moment it becomes real after a crash
            self._state = new_state
            self._versions.install(Version(
                number=current.number + 1, active=current.active,
                immutables=tuple(m for m in current.immutables if m is not flushed),
                windows=tuple((w, tuple(readers[w])) for w in order),
                newest_data_ts=new_state.newest_data_ts))
