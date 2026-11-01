"""Write one SSTable in a single front-to-back pass into <name>.tmp (implements ports.TableWriter).
The writer does NOT publish the file: TableFactory.publish renames it, then the caller commits
the MANIFEST."""

from __future__ import annotations

from pathlib import Path

from tsdb.model import Point, Tombstone
from tsdb.ports import FaultInjector, FileOps, MembershipFilterFactory


class SSTableWriter:
    def __init__(self, tmp_path: Path, files: FileOps, faults: FaultInjector,
                 filters: MembershipFilterFactory, block_target_bytes: int, filter_fp_rate: float) -> None:
        self._tmp_path = tmp_path
        self._files = files
        self._faults = faults
        self._filters = filters
        self._block_target_bytes = block_target_bytes
        self._filter_fp_rate = filter_fp_rate

    def add(self, point: Point) -> None:
        """Points must arrive in (series_id, timestamp) order, one version per key, all inside
        this file's window (checked: a point outside the window is a bug)."""
        raise NotImplementedError

    def add_tombstone(self, tombstone: Tombstone) -> None:
        """Already clipped to this file's window by the caller."""
        raise NotImplementedError

    def finish(self) -> Path:
        """Write tombstones, index, filter, footer; fsync; return the .tmp path.
        faults.hit(SSTABLE_WRITE) half way through the data blocks."""
        raise NotImplementedError

    def abort(self) -> None:
        raise NotImplementedError
