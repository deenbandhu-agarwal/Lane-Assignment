"""SSTable factory (implements ports.TableFactory). Flush, compaction and recovery depend on the
port, so the table format can be swapped (or faked in tests) from bootstrap."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tsdb.model import TimeWindow
from tsdb.ports import FaultInjector, FileOps, MembershipFilterFactory
from tsdb.sstable.reader import SSTableReader
from tsdb.sstable.writer import SSTableWriter

TablePathFn = Callable[[TimeWindow, int], Path]     # (window, file_no) -> final path


class SSTableFactory:
    def __init__(self, table_path: TablePathFn, files: FileOps, faults: FaultInjector,
                 filters: MembershipFilterFactory, block_target_bytes: int, filter_fp_rate: float) -> None:
        self._table_path = table_path
        self._files = files
        self._faults = faults
        self._filters = filters
        self._block_target_bytes = block_target_bytes
        self._filter_fp_rate = filter_fp_rate

    def new_writer(self, window: TimeWindow, file_no: int) -> SSTableWriter:
        final = self._table_path(window, file_no)
        tmp = final.with_name(final.name + ".tmp")
        return SSTableWriter(tmp, window, self._files, self._faults, self._filters,
                             self._block_target_bytes, self._filter_fp_rate)

    def publish(self, tmp_path: Path, window: TimeWindow, file_no: int) -> Path:
        """Rename .tmp -> final name, fsync the directory."""
        final = self._table_path(window, file_no)
        self._files.publish_tmp(tmp_path, final)
        return final

    def open_reader(self, path: Path, window: TimeWindow) -> SSTableReader:
        raise NotImplementedError
