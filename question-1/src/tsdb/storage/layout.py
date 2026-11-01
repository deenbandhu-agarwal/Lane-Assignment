"""Where every file lives inside one shard's data directory. Pure path arithmetic, no I/O
(directory creation and orphan cleanup go through ports.FileOps in Recovery).

    <shard_dir>/
      MANIFEST                 live files, wal_count, segment number, last seq
      series.log               series id <-> series key (append-only, framed records)
      wal/<i>/<segment>.log    WAL i of N, one segment per memtable
      sst/L<n>/<file_no>.sst   immutable sorted tables
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ShardLayout:
    root: Path

    @property
    def manifest(self) -> Path:
        raise NotImplementedError

    @property
    def series_log(self) -> Path:
        raise NotImplementedError

    def wal_segment(self, wal_index: int, segment: int) -> Path:
        raise NotImplementedError

    def sstable(self, level: int, file_no: int) -> Path:
        raise NotImplementedError

    def tmp_for(self, final_path: Path) -> Path:
        raise NotImplementedError
