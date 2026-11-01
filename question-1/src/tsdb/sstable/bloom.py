"""Bloom filter over series ids, from scratch (implements ports.MembershipFilter + factory).

Sizing for n items and false-positive rate p:
    m = ceil(-n * ln(p) / (ln 2)^2)      bits   (p = 1% -> ~9.59 bits per item)
    k = round((m / n) * ln 2)            hashes (p = 1% -> 7)
Hashes: double hashing h_i = (h1 + i * h2) mod m, from two independent 32-bit hashes.
Tombstone series ids are added too, so a filter "no" never hides a tombstone.
"""

from __future__ import annotations


class BloomFilter:
    def __init__(self, m_bits: int, k: int, bits: bytearray | None = None) -> None:
        self.m_bits = m_bits
        self.k = k
        self._bits = bits if bits is not None else bytearray((m_bits + 7) // 8)

    @staticmethod
    def optimal_params(n: int, p: float) -> tuple[int, int]:
        """Return (m_bits, k)."""
        raise NotImplementedError

    def add(self, series_id: int) -> None:
        raise NotImplementedError

    def may_contain(self, series_id: int) -> bool:
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        raise NotImplementedError


class BloomFilterFactory:
    def new(self, expected_items: int, false_positive_rate: float) -> BloomFilter:
        raise NotImplementedError

    def load(self, data: bytes) -> BloomFilter:
        raise NotImplementedError
