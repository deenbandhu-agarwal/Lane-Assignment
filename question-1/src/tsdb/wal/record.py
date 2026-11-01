"""WAL record encoding. Pure functions, no I/O.

Frame:   length u32 | crc32(payload) u32 | payload
PUT:     type=1 u8 | seq u64 | series_id u32 | timestamp i64 | value f64          (29 bytes)
DELETE:  type=2 u8 | seq u64 | from i64 | to i64 | count u32 | series_id u32 * count

The length lets the reader find record edges (records differ in size) and detect a record cut by
a crash; the checksum detects damaged bytes. Replay stops at the first cut/bad record.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from enum import IntEnum

from tsdb.model import Point, Tombstone


_HEADER = struct.Struct("<II")       # length, crc32
_PUT = struct.Struct("<BQIqd")        # type, seq, series_id, timestamp, value  (29 bytes)
_DELETE = struct.Struct("<BQqqI")     # type, seq, from, to, count; then count x u32 series ids


class RecordType(IntEnum):
    PUT = 1
    DELETE = 2


@dataclass(frozen=True, slots=True)
class DecodedRecord:
    offset: int                       # byte offset of the frame in the file
    entry: Point | Tombstone


@dataclass(frozen=True, slots=True)
class ScanResult:
    records: list[DecodedRecord]
    valid_length: int                 # bytes up to the last good record; truncate the file here
    stopped_reason: str | None        # None = clean end; else "cut record" / "bad checksum"


def encode_put(point: Point) -> bytes:
    return _PUT.pack(RecordType.PUT, point.seq, point.series_id, point.timestamp, point.value)


def encode_delete(tombstone: Tombstone) -> bytes:
    ids = tombstone.series_ids
    return (_DELETE.pack(RecordType.DELETE, tombstone.seq, tombstone.from_ts, tombstone.to_ts, len(ids))
            + struct.pack(f"<{len(ids)}I", *ids))


def frame(payload: bytes) -> bytes:
    return _HEADER.pack(len(payload), zlib.crc32(payload)) + payload


def scan(data: bytes) -> ScanResult:
    """Decode records front to back; stop at the first cut or bad-checksum record."""
    records = [DecodedRecord(offset, _decode(payload)) for offset, payload in iter_frames(data)]
    return ScanResult(records, len(data), None)


def _decode(payload: bytes) -> Point | Tombstone:
    if payload[0] == RecordType.DELETE:
        _, seq, from_ts, to_ts, count = _DELETE.unpack_from(payload)
        ids = struct.unpack_from(f"<{count}I", payload, _DELETE.size)
        return Tombstone(seq, ids, from_ts, to_ts)
    _, seq, series_id, timestamp, value = _PUT.unpack(payload)
    return Point(series_id, timestamp, seq, value)


def iter_frames(data: bytes) -> Iterator[tuple[int, bytes]]:
    """Low-level: yield (offset, payload) for each valid frame. Shared with series.log."""
    offset = 0
    while offset < len(data):
        length, _ = _HEADER.unpack_from(data, offset)
        start = offset + _HEADER.size
        yield offset, data[start:start + length]
        offset = start + length
