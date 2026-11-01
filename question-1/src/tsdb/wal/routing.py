"""WAL routing (implements ports.WalRouter).

Uses a STABLE hash (zlib.crc32 of the canonical key), never Python's built-in hash(), which is
randomised per process and would send a series to a different WAL after a restart.
"""

from __future__ import annotations

import zlib

from tsdb.model import SeriesKey


class HashWalRouter:
    def __init__(self, wal_count: int) -> None:
        self._wal_count = wal_count

    def route(self, key: SeriesKey) -> int:
        return zlib.crc32(key.canonical().encode()) % self._wal_count
