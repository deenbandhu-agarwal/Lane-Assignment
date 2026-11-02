"""Startup recovery for one shard. Runs before the shard accepts requests. Depends only on ports.

    1. manifest.load() (fresh dir -> empty state)
    2. remove orphans: *.tmp files and tables not in MANIFEST (half flushes / compactions)
    3. series.load() -> catalog + inverted index (cut tail record dropped)
    4. open live tables (footer, tail, checksums)
    5. replay the live WAL segments into a new memtable; truncate a cut tail
    6. seq = max(MANIFEST.last_flushed_seq, highest replayed seq)
    7. newest data time = max(MANIFEST.newest_data_ts, replayed timestamps), so window closing
       continues exactly where it stopped
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from tsdb.model import ManifestState, TimeWindow
from tsdb.storage.layout import ShardLayout
from tsdb.ports import FileOps, ManifestPort, MemtableFactory, MemtablePort, SeriesResolver, TableFactory, TableReader
from tsdb.wal.record import DecodedRecord

ReplayFn = Callable[[int], Iterator[DecodedRecord]]     # from_segment -> records


@dataclass(slots=True)
class RecoveredState:
    manifest: ManifestState
    windows: tuple[tuple[TimeWindow, tuple[TableReader, ...]], ...]
    memtable: MemtablePort                 # becomes the active memtable
    last_seq: int
    active_segment: int                    # new writes go here: one past every segment on disk
    removed_orphans: list[Path] = field(default_factory=list)
    replayed_records: int = 0


class Recovery:
    def __init__(self, layout: ShardLayout, manifest: ManifestPort, series: SeriesResolver, tables: TableFactory,
                 replay: ReplayFn, new_memtable: MemtableFactory, files: FileOps) -> None:
        self._layout = layout
        self._manifest = manifest
        self._series = series
        self._tables = tables
        self._replay = replay
        self._new_memtable = new_memtable
        self._files = files

    def run(self) -> RecoveredState:
        state = self._manifest.load() or ManifestState(version=0, next_file_no=1, last_flushed_seq=0,
                                                       wal_segment=1)
        self._series.load()
        removed = self._remove_flushed_segments(state.wal_segment) + self._remove_orphans(state)
        windows = tuple((w, tuple(self._tables.open_reader(self._layout.sstable(w, int(n[:6])), w)
                                  for n in reversed(names)))            # newest first
                        for w, names in state.windows)
        memtable = self._new_memtable()
        last_seq, replayed, newest_segment = state.last_flushed_seq, 0, state.wal_segment - 1
        for record in self._replay(state.wal_segment):
            memtable.apply([record.entry])
            last_seq = max(last_seq, record.entry.seq)
            replayed += 1
        segment = state.wal_segment
        while self._layout.wal_segment(segment).exists():
            newest_segment = segment
            segment += 1
        return RecoveredState(state, windows, memtable, last_seq, active_segment=newest_segment + 1,
                              removed_orphans=removed, replayed_records=replayed)

    def _remove_orphans(self, state: ManifestState) -> list[Path]:
        """*.tmp files (a write that never finished) and tables the MANIFEST does not list (a flush
        or compaction that crashed before its commit). Walks sst/<size>/<start>/ via FileOps."""
        live = {self._layout.sstable(w, int(n[:6])) for w, names in state.windows for n in names}
        removed = []
        manifest_tmp = self._layout.tmp_for(self._layout.manifest)
        if manifest_tmp.exists():
            self._files.remove(manifest_tmp)
            removed.append(manifest_tmp)
        for size_dir in self._files.list_dir(self._layout.root / "sst"):
            for window_dir in self._files.list_dir(size_dir):
                for path in self._files.list_dir(window_dir):
                    if path not in live:
                        self._files.remove(path)
                        removed.append(path)
        return removed

    def _remove_flushed_segments(self, first_live: int) -> list[Path]:
        """Segments below MANIFEST.wal_segment are already in tables (a crash between the MANIFEST
        commit and their deletion leaves them behind). Replaying them would be harmless but wasteful."""
        removed = []
        for path in self._files.list_dir(self._layout.wal_segment(0).parent):
            if path.suffix == ".log" and int(path.stem) < first_live:
                self._files.remove(path)
                removed.append(path)
        return removed
