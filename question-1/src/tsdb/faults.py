"""Crash points for fault-injection tests (implementations of ports.FaultInjector).

The engine calls `faults.hit(CrashPoint.X)` at each dangerous moment. Production wiring injects
NoFaults. Crash tests start the server with TSDB_CRASH_AT=<name> (optional TSDB_CRASH_AFTER=<n>)
and bootstrap injects EnvFaults, which SIGKILLs the process there, exactly like `kill -9`.
"""

from __future__ import annotations

import os
from enum import Enum


class CrashPoint(str, Enum):
    WAL_APPEND = "wal_append"            # after bytes written, before fsync completes
    MEMTABLE_FLUSH = "memtable_flush"    # memtable frozen, SSTable not yet started
    SSTABLE_WRITE = "sstable_write"      # half of the .tmp SSTable written
    MANIFEST_UPDATE = "manifest_update"  # MANIFEST.tmp written, not yet renamed
    COMPACTION_SWAP = "compaction_swap"  # new files written, MANIFEST not yet swapped


class NoFaults:
    def hit(self, point: str) -> None:
        return None


class EnvFaults:
    """SIGKILL self at `crash_at` after `after` hits."""

    def __init__(self, crash_at: str, after: int = 1) -> None:
        self._crash_at = crash_at
        self._after = after
        self._hits = 0

    @staticmethod
    def from_env() -> "NoFaults | EnvFaults":
        crash_at = os.environ.get("TSDB_CRASH_AT")
        if not crash_at:
            return NoFaults()
        raise NotImplementedError("crash harness: designed before the crash tests")

    def hit(self, point: str) -> None:
        raise NotImplementedError
