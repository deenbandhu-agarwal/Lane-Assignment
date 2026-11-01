"""WalSet (implements ports.WalPort): N WAL files in parallel; one series always goes to the same
WAL (injected WalRouter).

- write(): split a batch by WAL, submit one Ticket per WAL, wait for ALL tickets (then 200 OK).
  A crash between tickets may leave part of a batch on disk: allowed, no OK was sent.
- delete(): a tombstone goes to EVERY WAL that holds one of its series, so each file replays alone.
- rotate_all(): on memtable swap, pause all writers, start a new segment in every WAL, resume.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from tsdb.model import SeriesId, SeriesKey, Timestamp
from tsdb.ports import FileOps, MemtablePort, WalRouter
from tsdb.wal.record import DecodedRecord
from tsdb.wal.segment import WalSegment
from tsdb.wal.writer import WalWriter

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
        raise NotImplementedError

    def delete(self, keys_and_ids: list[tuple[SeriesKey, SeriesId]], from_ts: Timestamp, to_ts: Timestamp) -> None:
        raise NotImplementedError

    def rotate_all(self, new_segment_no: int, new_memtable: MemtablePort) -> list[Path]:
        """Returns old segment paths (deleted after the flush's MANIFEST commit)."""
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class WalReplayer:
    """Recovery: read every live segment of every WAL; truncate cut tails. Order between WALs does
    not matter (no series spans two WALs)."""

    def __init__(self, files: FileOps, segment_path: SegmentPathFn) -> None:
        self._files = files
        self._segment_path = segment_path

    def replay(self, wal_count: int, from_segment: int) -> Iterator[DecodedRecord]:
        raise NotImplementedError


def new_segment(path: Path, files: FileOps) -> WalSegment:
    raise NotImplementedError
