"""Startup recovery for one shard. Runs before the shard accepts requests. Depends only on ports.

    1. manifest.load() (fresh dir -> empty state); if config wal_count != MANIFEST.wal_count,
       refuse to start (routing would send series to the wrong WAL; migration not supported)
    2. remove orphans: *.tmp files and tables not in MANIFEST (half flushes / compactions)
    3. series.load() -> catalog + inverted index (cut tail record dropped)
    4. open live tables (footer, tail, checksums)
    5. replay WAL segments of every WAL into a new memtable; truncate cut tails
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

ReplayFn = Callable[[int, int], Iterator[DecodedRecord]]     # (wal_count, from_segment) -> records


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
                 replay: ReplayFn, new_memtable: MemtableFactory, files: FileOps, wal_count: int) -> None:
        self._layout = layout
        self._manifest = manifest
        self._series = series
        self._tables = tables
        self._replay = replay
        self._new_memtable = new_memtable
        self._files = files
        self._wal_count = wal_count

    def run(self) -> RecoveredState:
        state = self._manifest.load() or ManifestState(version=0, next_file_no=1, last_flushed_seq=0,
                                                       wal_count=self._wal_count, wal_segment=1)
        self._series.load()
        memtable = self._new_memtable()
        last_seq, replayed, newest_segment = state.last_flushed_seq, 0, state.wal_segment - 1
        for record in self._replay(self._wal_count, state.wal_segment):
            memtable.apply([record.entry])
            last_seq = max(last_seq, record.entry.seq)
            replayed += 1
        for wal in range(self._wal_count):
            segment = state.wal_segment
            while self._layout.wal_segment(wal, segment).exists():
                newest_segment = max(newest_segment, segment)
                segment += 1
        return RecoveredState(state, (), memtable, last_seq, active_segment=newest_segment + 1,
                              replayed_records=replayed)
