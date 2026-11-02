"""Where every file lives inside one shard's data directory. Pure path arithmetic, no I/O
(directory creation and orphan cleanup go through ports.FileOps in Recovery).

    <shard_dir>/
      MANIFEST                 live files, WAL segment number, last flushed seq
      series.log               series id <-> series key (append-only, framed records)
      wal/<segment>.log        the WAL, one segment per memtable
      sst/<size_ms>/<start_ms>/<file_no>.sst   immutable sorted tables, one time window each
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tsdb.model import TimeWindow


@dataclass(frozen=True, slots=True)
class ShardLayout:
    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "MANIFEST"

    @property
    def series_log(self) -> Path:
        return self.root / "series.log"

    def wal_segment(self, segment: int) -> Path:
        return self.root / "wal" / f"{segment:06d}.log"

    def sstable(self, window: TimeWindow, file_no: int) -> Path:
        return self.root / "sst" / window.label() / f"{file_no:06d}.sst"

    def tmp_for(self, final_path: Path) -> Path:
        return final_path.with_name(final_path.name + ".tmp")
