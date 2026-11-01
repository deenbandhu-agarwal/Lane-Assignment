"""Read one SSTable (implements ports.TableReader).

open: read the footer (last FOOTER_SIZE bytes), then the contiguous tail; keep sparse index,
membership filter, per-series tombstone map and footer stats in memory. Data blocks stay on disk.
The file never changes after publish, so reads are snapshot-safe; lifetime is handled by
engine.version reference counting.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from tsdb.model import Point, SeriesId, Timestamp, Tombstone
from tsdb.ports import FileOps, MembershipFilterFactory


class SSTableReader:
    def __init__(self, path: Path, level: int, files: FileOps, filters: MembershipFilterFactory) -> None:
        self._path = path
        self._level = level
        self._files = files
        self._filters = filters

    def open(self) -> None:
        """Validates magic + checksums; raises CorruptFileError."""
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self._path.name

    @property
    def level(self) -> int:
        return self._level

    def may_contain(self, series_id: SeriesId, from_ts: Timestamp, to_ts: Timestamp) -> bool:
        """Footer min/max (series and time), then the membership filter. False = surely not here."""
        raise NotImplementedError

    def tombstones_for(self, series_id: SeriesId) -> list[Tombstone]:
        raise NotImplementedError

    def cursor(self) -> "ForwardCursor":
        raise NotImplementedError

    def iter_all(self) -> Iterator[Point]:
        raise NotImplementedError

    def all_tombstones(self) -> list[Tombstone]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class ForwardCursor:
    """Implements ports.TableCursor for SSTables. Binary-searches the sparse index for
    (series_id, from_ts), reads block(s) in file order only, verifies checksums, stops when
    key > (series_id, to_ts), and keeps the last block so neighbour series reuse it."""

    def __init__(self, reader: SSTableReader) -> None:
        self._reader = reader

    def read_series(self, series_id: SeriesId, from_ts: Timestamp, to_ts: Timestamp) -> Iterator[Point]:
        raise NotImplementedError

    @property
    def blocks_read(self) -> int:
        raise NotImplementedError
