"""Bloom filter over series ids, from scratch (implements ports.MembershipFilter + factory).

Sizing for n items and false-positive rate p:
    m = ceil(-n * ln(p) / (ln 2)^2)      bits, rounded up to whole bytes (p = 1% -> ~9.59 bits per item)
    k = round((m / n) * ln 2)            hashes (p = 1% -> 7)
Hashes: double hashing h_i = (h1 + i * h2) mod m; h1 = FNV-1a, h2 = crc32 | 1 (of the u32 id).
Tombstone series ids are added too, so a filter "no" never hides a tombstone.
"""

from __future__ import annotations

import math
import struct
import zlib


def _fnv1a(data: bytes) -> int:
    h = 0x811C9DC5
    for byte in data:
        h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
    return h


class BloomFilter:
    def __init__(self, m_bits: int, k: int, bits: bytearray | None = None) -> None:
        self.m_bits = m_bits
        self.k = k
        self._bits = bits if bits is not None else bytearray((m_bits + 7) // 8)

    @staticmethod
    def optimal_params(n: int, p: float) -> tuple[int, int]:
        """Return (m_bits, k). m is rounded up to whole bytes (the file stores whole bytes anyway).
        n < 1 is treated as 1 (a file always holds at least one series id)."""
        n = max(1, n)
        m = math.ceil(-n * math.log(p) / math.log(2) ** 2)
        m = (m + 7) // 8 * 8
        return m, max(1, round(m / n * math.log(2)))

    def add(self, series_id: int) -> None:
        for bit in self._positions(series_id):
            self._bits[bit >> 3] |= 1 << (bit & 7)

    def may_contain(self, series_id: int) -> bool:
        return all(self._bits[bit >> 3] & (1 << (bit & 7)) for bit in self._positions(series_id))

    def _positions(self, series_id: int) -> list[int]:
        """Double hashing over the 4 little-endian bytes of the id: h1 = FNV-1a, h2 = crc32 | 1
        (odd, so the k positions differ)."""
        data = struct.pack("<I", series_id)
        h1, h2 = _fnv1a(data), zlib.crc32(data) | 1
        return [(h1 + i * h2) % self.m_bits for i in range(self.k)]

    def to_bytes(self) -> bytes:
        raise NotImplementedError


class BloomFilterFactory:
    def new(self, expected_items: int, false_positive_rate: float) -> BloomFilter:
        raise NotImplementedError

    def load(self, data: bytes) -> BloomFilter:
        raise NotImplementedError
