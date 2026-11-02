"""SSTable byte layout (little-endian). Single source of truth for sizes; writer and reader import it.

    HEADER        magic 'TSST' | version u16 | reserved u16                          8 bytes
    DATA BLOCK*   count u32 | entry * count | crc32 u32          entry = 28 bytes:
                     series_id u32 | timestamp i64 | seq u64 | value f64
    TOMBSTONES    count u32 | (seq u64 | from i64 | to i64 | n u32 | series_id u32 * n)* | crc32
    SPARSE INDEX  count u32 | (first series_id u32 | first ts i64 | offset u64 | length u32)* | crc32
    BLOOM         m_bits u32 | k u8 | bits | crc32
    FOOTER        fixed size, read FIRST (seek to file_size - FOOTER_SIZE):
                     index off u64, len u32 | bloom off u64, len u32 | tombs off u64, len u32 |
                     min_ts i64 | max_ts i64 | min_sid u32 | max_sid u32 | count u32 |
                     version u16 | crc32 u32 | magic 'TSST'

Tombstones, index, Bloom and footer are contiguous at the tail: open = 2 reads (footer, then tail).
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from tsdb.errors import CorruptFileError

MAGIC = b"TSST"
VERSION = 1

HEADER = struct.Struct("<4sHH")
ENTRY = struct.Struct("<IqQd")
BLOCK_COUNT = struct.Struct("<I")
CRC = struct.Struct("<I")
INDEX_ENTRY = struct.Struct("<IqQI")
FOOTER = struct.Struct("<QIQIQIqqIIIHI4s")
FOOTER_SIZE = FOOTER.size     # 74 bytes (72 + 2-byte version inside the footer)
_FOOTER_CRC_AT = FOOTER_SIZE - 8    # crc32 covers every footer byte before the crc itself
TOMBSTONE_HEAD = struct.Struct("<QqqI")   # seq, from, to, n; then n x u32 series ids


@dataclass(frozen=True, slots=True)
class Footer:
    index_offset: int
    index_length: int
    bloom_offset: int
    bloom_length: int
    tombstones_offset: int
    tombstones_length: int
    min_ts: int
    max_ts: int
    min_series_id: int
    max_series_id: int
    point_count: int
    version: int

    def pack(self) -> bytes:
        fields = (self.index_offset, self.index_length, self.bloom_offset, self.bloom_length,
                  self.tombstones_offset, self.tombstones_length, self.min_ts, self.max_ts,
                  self.min_series_id, self.max_series_id, self.point_count, self.version)
        body = FOOTER.pack(*fields, 0, MAGIC)[:_FOOTER_CRC_AT]
        return FOOTER.pack(*fields, zlib.crc32(body), MAGIC)

    @staticmethod
    def unpack(data: bytes) -> "Footer":
        """Checks magic + checksum; raises CorruptFileError."""
        if len(data) != FOOTER_SIZE:
            raise CorruptFileError(f"footer is {len(data)} bytes, expected {FOOTER_SIZE}")
        *fields, crc, magic = FOOTER.unpack(data)
        if magic != MAGIC:
            raise CorruptFileError(f"bad footer magic {magic!r}")
        if zlib.crc32(data[:_FOOTER_CRC_AT]) != crc:
            raise CorruptFileError("footer checksum mismatch")
        return Footer(*fields)


@dataclass(frozen=True, slots=True)
class IndexEntry:
    first_series_id: int
    first_timestamp: int
    offset: int
    length: int
