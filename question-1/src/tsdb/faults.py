"""Crash points for fault-injection tests (implementations of ports.FaultInjector).

The engine calls `faults.hit(CrashPoint.X)` at each dangerous moment. Production wiring injects
NoFaults. Crash tests start the server with TSDB_CRASH_AT=<name> (optional TSDB_CRASH_AFTER=<n>)
and bootstrap injects EnvFaults, which SIGKILLs the process there, exactly like `kill -9`.
"""

from __future__ import annotations

import os
import signal
import threading
from collections.abc import Callable
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
    """SIGKILL self at the `after`-th hit of `crash_at`. No cleanup, no flush, no atexit: the
    process just stops, exactly like `kill -9` (the OS page cache survives: not a power cut)."""

    def __init__(self, crash_at: str, after: int = 1, kill: Callable[[], None] | None = None) -> None:
        self._crash_at = CrashPoint(crash_at)
        self._after = after
        self._hits = 0
        self._kill = kill or _sigkill_self
        self._lock = threading.Lock()                # WAL writers and flush hit from many threads

    @staticmethod
    def from_env(kill: Callable[[], None] | None = None) -> "NoFaults | EnvFaults":
        crash_at = os.environ.get("TSDB_CRASH_AT")
        if not crash_at:
            return NoFaults()
        if crash_at not in {p.value for p in CrashPoint}:
            raise ValueError(f"TSDB_CRASH_AT={crash_at!r}: use one of {', '.join(p.value for p in CrashPoint)}")
        return EnvFaults(crash_at, int(os.environ.get("TSDB_CRASH_AFTER", "1")), kill)

    def hit(self, point: str) -> None:
        if point != self._crash_at:
            return
        with self._lock:
            self._hits += 1
            if self._hits == self._after:
                self._kill()


def _sigkill_self() -> None:
    os.kill(os.getpid(), signal.SIGKILL)
