"""WalSet (implements ports.WalPort): N WAL files in parallel; one series always goes to the same
WAL (injected WalRouter).

- write(): split a batch by WAL, submit one Ticket per WAL, wait for ALL tickets (then 200 OK).
  A crash between tickets may leave part of a batch on disk: allowed, no OK was sent.
- delete(): a tombstone goes to EVERY WAL that holds one of its series, so each file replays alone.
  Each copy names ONLY that WAL's series and gets that WAL's seq: a series lives in one WAL, so
  "written before the delete" only needs that WAL's order.
- rotate_all(): on memtable swap (caller holds SwapLock.exclusive, so no group is in flight):
  start a new segment in every WAL and point every writer at the new memtable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from tsdb.model import SeriesId, SeriesKey, Timestamp
from tsdb.ports import FileOps, MemtablePort, WalRouter
from tsdb.wal.record import DecodedRecord
from tsdb.wal.segment import WalSegment
from tsdb.wal.record import scan
from tsdb.wal.writer import PendingDelete, PendingPut, Ticket, WalWriter

SegmentPathFn = Callable[[int, int], Path]     # (wal_index, segment_no) -> path


class WalSet:
    def __init__(self, writers: list[WalWriter], router: WalRouter, segment_path: SegmentPathFn,
                 files: FileOps) -> None:
        self._writers = writers
        self._router = router
        self._segment_path = segment_path
        self._files = files

    def write(self, puts: list[tuple[SeriesKey, SeriesId, Timestamp, float]]) -> None:
        """Blocks until every affected WAL has fsynced and applied its part."""
        per_wal: dict[int, list[PendingPut]] = {}
        for key, series_id, timestamp, value in puts:
            per_wal.setdefault(self._router.route(key), []).append(PendingPut(series_id, timestamp, value))
        self._submit_and_wait({wal: Ticket(list(entries)) for wal, entries in per_wal.items()})

    def delete(self, keys_and_ids: list[tuple[SeriesKey, SeriesId]], from_ts: Timestamp, to_ts: Timestamp) -> None:
        per_wal: dict[int, list[SeriesId]] = {}
        for key, series_id in keys_and_ids:
            per_wal.setdefault(self._router.route(key), []).append(series_id)
        self._submit_and_wait({wal: Ticket([PendingDelete(tuple(sorted(ids)), from_ts, to_ts)])
                               for wal, ids in per_wal.items()})

    def rotate_all(self, new_segment_no: int, new_memtable: MemtablePort) -> list[Path]:
        """Returns old segment paths (deleted after the flush's MANIFEST commit)."""
        old_paths = []
        for i, writer in enumerate(self._writers):
            old = writer.switch_segment(new_segment(self._segment_path(i, new_segment_no), self._files))
            old.close()
            old_paths.append(old.path)
            writer.set_apply(new_memtable.apply)
        return old_paths

    def close(self) -> None:
        for writer in self._writers:
            writer.stop()

    def _submit_and_wait(self, tickets: dict[int, Ticket]) -> None:
        for wal, ticket in tickets.items():
            self._writers[wal].submit(ticket)
        for ticket in tickets.values():
            ticket.done.wait()
        for ticket in tickets.values():
            if ticket.error is not None:
                raise ticket.error


class WalReplayer:
    """Recovery: read every live segment of every WAL; truncate cut tails. Order between WALs does
    not matter (no series spans two WALs)."""

    def __init__(self, files: FileOps, segment_path: SegmentPathFn) -> None:
        self._files = files
        self._segment_path = segment_path

    def replay(self, wal_count: int, from_segment: int) -> Iterator[DecodedRecord]:
        """Segments from_segment, from_segment + 1, ... of every WAL, until one is missing.
        A cut tail is truncated so the next append starts on a clean record edge."""
        for wal in range(wal_count):
            segment_no = from_segment
            while (path := self._segment_path(wal, segment_no)).exists():
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
