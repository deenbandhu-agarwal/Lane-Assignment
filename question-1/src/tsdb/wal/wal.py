"""Wal (implements ports.WalPort): the shard's ONE write-ahead log, over one group-commit writer.

- write() / delete(): one Ticket, wait until it is fsynced and applied (then 200 OK).
- rotate(): on memtable swap (caller holds the swap lock, so no group is in flight): start a
  new segment and point the writer at the new memtable. Returns the old segment's path, deleted
  after the flush's MANIFEST commit.
One WAL, not N: measured faster on this machine (design-qa #54), and simpler: no routing, no
per-WAL copies of a delete, groups apply in seq order.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from tsdb.model import SeriesId, Timestamp
from tsdb.ports import FileOps, MemtablePort
from tsdb.wal.record import DecodedRecord, scan
from tsdb.wal.segment import WalSegment
from tsdb.wal.writer import PendingDelete, PendingPut, Ticket, WalWriter

SegmentPathFn = Callable[[int], Path]     # segment_no -> path


class Wal:
    def __init__(self, writer: WalWriter, segment_path: SegmentPathFn, files: FileOps) -> None:
        self._writer = writer
        self._segment_path = segment_path
        self._files = files

    def write(self, puts: list[tuple[SeriesId, Timestamp, float]]) -> None:
        """Blocks until fsynced and applied."""
        self._submit_and_wait(Ticket([PendingPut(series_id, ts, value) for series_id, ts, value in puts]))

    def delete(self, series_ids: list[SeriesId], from_ts: Timestamp, to_ts: Timestamp) -> None:
        self._submit_and_wait(Ticket([PendingDelete(tuple(sorted(series_ids)), from_ts, to_ts)]))

    def rotate(self, new_segment_no: int, new_memtable: MemtablePort) -> Path:
        old = self._writer.switch_segment(new_segment(self._segment_path(new_segment_no), self._files))
        old.close()
        self._writer.set_apply(new_memtable.apply)
        return old.path

    def close(self) -> None:
        self._writer.stop()

    def _submit_and_wait(self, ticket: Ticket) -> None:
        self._writer.submit(ticket)
        ticket.done.wait()
        if ticket.error is not None:
            raise ticket.error


class WalReplayer:
    """Recovery: read every live segment in order; truncate a cut tail."""

    def __init__(self, files: FileOps, segment_path: SegmentPathFn) -> None:
        self._files = files
        self._segment_path = segment_path

    def replay(self, from_segment: int) -> Iterator[DecodedRecord]:
        """Segments from_segment, from_segment + 1, ... until one is missing. A cut tail is
        truncated so the next append starts on a clean record edge."""
        segment_no = from_segment
        while (path := self._segment_path(segment_no)).exists():
            data = self._files.read_all(path)
            result = scan(data)
            if result.valid_length < len(data):
                self._files.truncate(path, result.valid_length)
            yield from result.records
            segment_no += 1


def new_segment(path: Path, files: FileOps) -> WalSegment:
    segment = WalSegment(path, files)
    segment.open()
    return segment
