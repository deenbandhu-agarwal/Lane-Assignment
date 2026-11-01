"""WAL record encoding. Pure functions, no I/O.

Frame:   length u32 | crc32(payload) u32 | payload
PUT:     type=1 u8 | seq u64 | series_id u32 | timestamp i64 | value f64          (29 bytes)
DELETE:  type=2 u8 | seq u64 | from i64 | to i64 | count u32 | series_id u32 * count

The length lets the reader find record edges (records differ in size) and detect a record cut by
a crash; the checksum detects damaged bytes. Replay stops at the first cut/bad record.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import IntEnum

from tsdb.model import Point, Tombstone


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
    raise NotImplementedError


def encode_delete(tombstone: Tombstone) -> bytes:
    raise NotImplementedError


def frame(payload: bytes) -> bytes:
    raise NotImplementedError


def scan(data: bytes) -> ScanResult:
    """Decode records front to back; stop at the first cut or bad-checksum record."""
    raise NotImplementedError


def iter_frames(data: bytes) -> Iterator[tuple[int, bytes]]:
    """Low-level: yield (offset, payload) for each valid frame. Shared with series.log."""
    raise NotImplementedError
