"""Read one SSTable (implements ports.TableReader).

open: read the footer (last FOOTER_SIZE bytes), then the contiguous tail; keep sparse index,
membership filter, per-series tombstone map and footer stats in memory. Data blocks stay on disk.
The file never changes after publish, so reads are snapshot-safe; lifetime is handled by
engine.version reference counting.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from tsdb.model import Point, SeriesId, TimeWindow, Timestamp, Tombstone
from tsdb.ports import FileOps, MembershipFilter, MembershipFilterFactory
from tsdb.sstable.format import (BLOCK_COUNT, CRC, ENTRY, FOOTER_SIZE, INDEX_ENTRY, TOMBSTONE_HEAD, Footer,
                                 IndexEntry)


class SSTableReader:
    def __init__(self, path: Path, window: TimeWindow, files: FileOps, filters: MembershipFilterFactory) -> None:
        self._path = path
        self._window = window
        self._files = files
        self._filters = filters
        self._size = 0
        self._footer: Footer | None = None
        self._index: list[IndexEntry] = []
        self._filter: MembershipFilter | None = None
        self._tombstones: list[Tombstone] = []
        self._tombstones_by_series: dict[SeriesId, list[Tombstone]] = {}

    def open(self) -> None:
        """Validates magic + checksums; raises CorruptFileError.
        2 reads: the fixed-size footer, then the contiguous tail (tombstones, index, filter)."""
        self._size = self._files.size(self._path)
        footer = Footer.unpack(self._files.read_range(self._path, self._size - FOOTER_SIZE, FOOTER_SIZE))
        tail_start = footer.tombstones_offset
        tail = self._files.read_range(self._path, tail_start, self._size - FOOTER_SIZE - tail_start)

        def block(offset: int, length: int) -> bytes:
            return _body(tail[offset - tail_start:offset - tail_start + length])

        self._footer = footer
        self._tombstones = _parse_tombstones(block(footer.tombstones_offset, footer.tombstones_length))
        for t in self._tombstones:
            for series_id in t.series_ids:
                self._tombstones_by_series.setdefault(series_id, []).append(t)
        index = block(footer.index_offset, footer.index_length)
        (count,) = BLOCK_COUNT.unpack_from(index)
        self._index = [IndexEntry(*INDEX_ENTRY.unpack_from(index, BLOCK_COUNT.size + i * INDEX_ENTRY.size))
                       for i in range(count)]
        self._filter = self._filters.load(block(footer.bloom_offset, footer.bloom_length))

    def read_block(self, entry: IndexEntry) -> list[Point]:
        """One data block from disk, decoded."""
        body = _body(self._files.read_range(self._path, entry.offset, entry.length))
        (count,) = BLOCK_COUNT.unpack_from(body)
        return [Point(sid, ts, seq, value) for sid, ts, seq, value in
                (ENTRY.unpack_from(body, BLOCK_COUNT.size + i * ENTRY.size) for i in range(count))]

    @property
    def name(self) -> str:
        return self._path.name

    @property
    def window(self) -> TimeWindow:
        return self._window

    @property
    def min_ts(self) -> Timestamp:
        return self._footer.min_ts

    @property
    def max_ts(self) -> Timestamp:
        return self._footer.max_ts

    @property
    def size_bytes(self) -> int:
        return self._size

    def may_contain(self, series_id: SeriesId, from_ts: Timestamp, to_ts: Timestamp) -> bool:
        """Footer min/max (series and time), then the membership filter. False = surely not here."""
        raise NotImplementedError

    def tombstones_for(self, series_id: SeriesId) -> list[Tombstone]:
        return self._tombstones_by_series.get(series_id, [])

    def cursor(self) -> "ForwardCursor":
        raise NotImplementedError

    def iter_all(self) -> Iterator[Point]:
        for entry in self._index:
            yield from self.read_block(entry)

    def all_tombstones(self) -> list[Tombstone]:
        return list(self._tombstones)

    def close(self) -> None:
        """Nothing held open: every read opens, preads and closes (see OsFileOps.read_range)."""


def _body(block: bytes) -> bytes:
    """Block without its trailing crc32."""
    return block[:-CRC.size]


def _parse_tombstones(body: bytes) -> list[Tombstone]:
    (count,) = BLOCK_COUNT.unpack_from(body)
    offset, out = BLOCK_COUNT.size, []
    for _ in range(count):
        seq, from_ts, to_ts, n = TOMBSTONE_HEAD.unpack_from(body, offset)
        offset += TOMBSTONE_HEAD.size
        ids = tuple(BLOCK_COUNT.unpack_from(body, offset + i * 4)[0] for i in range(n))
        offset += 4 * n
        out.append(Tombstone(seq, ids, from_ts, to_ts))
    return out


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
