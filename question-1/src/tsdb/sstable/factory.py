"""SSTable factory (implements ports.TableFactory). Flush, compaction and recovery depend on the
port, so the table format can be swapped (or faked in tests) from bootstrap."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tsdb.ports import FaultInjector, FileOps, MembershipFilterFactory
from tsdb.sstable.reader import SSTableReader
from tsdb.sstable.writer import SSTableWriter

TablePathFn = Callable[[int, int], Path]     # (level, file_no) -> final path


class SSTableFactory:
    def __init__(self, table_path: TablePathFn, files: FileOps, faults: FaultInjector,
                 filters: MembershipFilterFactory, block_target_bytes: int, filter_fp_rate: float) -> None:
        self._table_path = table_path
        self._files = files
        self._faults = faults
        self._filters = filters
        self._block_target_bytes = block_target_bytes
        self._filter_fp_rate = filter_fp_rate

    def new_writer(self, level: int, file_no: int) -> SSTableWriter:
        raise NotImplementedError

    def publish(self, tmp_path: Path, level: int, file_no: int) -> Path:
        """Rename .tmp -> final name, fsync the directory."""
        raise NotImplementedError

    def open_reader(self, path: Path, level: int) -> SSTableReader:
        raise NotImplementedError
