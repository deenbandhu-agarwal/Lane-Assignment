"""Startup recovery for one shard. Runs before the shard accepts requests. Depends only on ports.

    1. manifest.load() (fresh dir -> empty state)
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
from tsdb.ports import FileOps, ManifestPort, MemtableFactory, MemtablePort, SeriesResolver, TableFactory, TableReader
from tsdb.wal.record import DecodedRecord

ReplayFn = Callable[[int, int], Iterator[DecodedRecord]]     # (wal_count, from_segment) -> records


@dataclass(slots=True)
class RecoveredState:
    manifest: ManifestState
    windows: tuple[tuple[TimeWindow, tuple[TableReader, ...]], ...]
    memtable: MemtablePort
    last_seq: int
    removed_orphans: list[Path] = field(default_factory=list)
    replayed_records: int = 0
    truncated_wal_bytes: int = 0


class Recovery:
    def __init__(self, root: Path, manifest: ManifestPort, series: SeriesResolver, tables: TableFactory,
                 replay: ReplayFn, new_memtable: MemtableFactory, files: FileOps, wal_count: int) -> None:
        self._root = root
        self._manifest = manifest
        self._series = series
        self._tables = tables
        self._replay = replay
        self._new_memtable = new_memtable
        self._files = files
        self._wal_count = wal_count

    def run(self) -> RecoveredState:
        raise NotImplementedError
