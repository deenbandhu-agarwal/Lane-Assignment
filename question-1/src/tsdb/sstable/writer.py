"""Write one SSTable in a single front-to-back pass into <name>.tmp (implements ports.TableWriter).
The writer does NOT publish the file: TableFactory.publish renames it, then the caller commits
the MANIFEST."""

from __future__ import annotations

import zlib
from pathlib import Path

from tsdb.faults import CrashPoint
from tsdb.model import Point, TimeWindow, Tombstone
from tsdb.ports import FaultInjector, FileOps, MembershipFilterFactory
from tsdb.sstable.format import (BLOCK_COUNT, CRC, ENTRY, HEADER, INDEX_ENTRY, MAGIC, TOMBSTONE_HEAD,
                                 VERSION, Footer)


def _with_crc(body: bytes) -> bytes:
    return body + CRC.pack(zlib.crc32(body))


class SSTableWriter:
    def __init__(self, tmp_path: Path, window: TimeWindow, files: FileOps, faults: FaultInjector,
                 filters: MembershipFilterFactory, block_target_bytes: int, filter_fp_rate: float) -> None:
        self._tmp_path = tmp_path
        self._window = window
        self._files = files
        self._faults = faults
        self._filters = filters
        self._block_target_bytes = block_target_bytes
        self._filter_fp_rate = filter_fp_rate
        self._fd = files.open_append(tmp_path)
        self._offset = 0
        self._block: list[Point] = []
        self._index: list[tuple[int, int, int, int]] = []     # first sid, first ts, offset, length
        self._tombstones: list[Tombstone] = []
        self._series_ids: set[int] = set()
        self._last_key: tuple[int, int] | None = None
        self._point_count = 0
        self._min_ts: int | None = None
        self._max_ts: int | None = None
        self._write(HEADER.pack(MAGIC, VERSION, 0))

    def add(self, point: Point) -> None:
        """Points must arrive in (series_id, timestamp) order, one version per key, all inside
        this file's window (checked: a point outside the window is a bug)."""
        key = (point.series_id, point.timestamp)
        if self._last_key is not None and key <= self._last_key:
            raise ValueError(f"point {key} not after {self._last_key}: input must be sorted, one version per key")
        if not self._window.contains(point.timestamp):
            raise ValueError(f"point at {point.timestamp} is outside window {self._window}")
        self._last_key = key
        self._block.append(point)
        self._note(point.series_id, point.timestamp, point.timestamp)
        self._point_count += 1
        if len(self._block) * ENTRY.size >= self._block_target_bytes:
            self._flush_block()

    def add_tombstone(self, tombstone: Tombstone) -> None:
        """Already clipped to this file's window by the caller."""
        if not (self._window.contains(tombstone.from_ts) and self._window.contains(tombstone.to_ts)):
            raise ValueError(f"tombstone {tombstone} is not clipped to window {self._window}")
        self._tombstones.append(tombstone)
        for series_id in tombstone.series_ids:
            self._note(series_id, tombstone.from_ts, tombstone.to_ts)

    def finish(self) -> Path:
        """Write the last block, then tombstones, index, filter, footer; fsync; return the .tmp path.
        faults.hit(SSTABLE_WRITE) after the data blocks, before the tail (= a half-written file)."""
        self._flush_block()
        self._faults.hit(CrashPoint.SSTABLE_WRITE)
        tomb_offset, tomb = self._offset, self._tombstone_block()
        self._write(tomb)
        index_offset, index = self._offset, self._index_block()
        self._write(index)
        bloom_offset, bloom = self._offset, self._bloom_block()
        self._write(bloom)
        ids = self._series_ids or {0}
        self._write(Footer(index_offset, len(index), bloom_offset, len(bloom), tomb_offset, len(tomb),
                           self._min_ts or 0, self._max_ts or 0, min(ids), max(ids),
                           self._point_count, VERSION).pack())
        self._files.fsync(self._fd)
        self._files.close(self._fd)
        return self._tmp_path

    def abort(self) -> None:
        self._files.close(self._fd)
        self._files.remove(self._tmp_path)

    def _note(self, series_id: int, from_ts: int, to_ts: int) -> None:
        self._series_ids.add(series_id)
        self._min_ts = from_ts if self._min_ts is None else min(self._min_ts, from_ts)
        self._max_ts = to_ts if self._max_ts is None else max(self._max_ts, to_ts)

    def _flush_block(self) -> None:
        if not self._block:
            return
        body = _with_crc(BLOCK_COUNT.pack(len(self._block)) + b"".join(
            ENTRY.pack(p.series_id, p.timestamp, p.seq, p.value) for p in self._block))
        first = self._block[0]
        self._index.append((first.series_id, first.timestamp, self._offset, len(body)))
        self._write(body)
        self._block = []

    def _tombstone_block(self) -> bytes:
        parts = [BLOCK_COUNT.pack(len(self._tombstones))]
        for t in self._tombstones:
            parts.append(TOMBSTONE_HEAD.pack(t.seq, t.from_ts, t.to_ts, len(t.series_ids)))
            parts.extend(BLOCK_COUNT.pack(i) for i in t.series_ids)
        return _with_crc(b"".join(parts))

    def _index_block(self) -> bytes:
        return _with_crc(BLOCK_COUNT.pack(len(self._index)) + b"".join(INDEX_ENTRY.pack(*e) for e in self._index))

    def _bloom_block(self) -> bytes:
        bloom = self._filters.new(len(self._series_ids), self._filter_fp_rate)
        for series_id in sorted(self._series_ids):
            bloom.add(series_id)
        return _with_crc(bloom.to_bytes())

    def _write(self, data: bytes) -> None:
        self._files.append(self._fd, data)
        self._offset += len(data)
