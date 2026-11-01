"""Background work on TWO threads, so writes and queries never do it inline (design-qa #45, D3).

    flush thread       flush when the active memtable is full (estimated bytes or max entries) OR
                       its oldest window is closed, so old data does not live only in memory + WAL
    compaction thread  run one job at a time while the policy picks one

Two threads so a long move-up compaction (a whole day) never blocks a flush. They meet only at
VersionSet.install (small lock).

Backpressure: at most `max_immutable_memtables` (1) frozen memtables wait for flush. If the active
one is full too, `wait_for_room()` blocks writers until the flush finishes: a slow disk makes writes
slower instead of using unbounded memory.
Depends on the Flusher, Compactor and CompactionPolicy it is given (no Shard).
"""

from __future__ import annotations

import threading

from tsdb.compaction.compactor import Compactor
from tsdb.compaction.policy import CompactionPolicy
from tsdb.engine.flush import Flusher
from tsdb.engine.version import VersionSet
from tsdb.model import TimeWindow


class BackgroundWorker:
    def __init__(self, versions: VersionSet, flusher: Flusher, compactor: Compactor,
                 policy: CompactionPolicy, max_immutable_memtables: int, smallest_window_ms: int) -> None:
        self._smallest_window_ms = smallest_window_ms
        self._versions = versions
        self._flusher = flusher
        self._compactor = compactor
        self._policy = policy
        self._max_immutable = max_immutable_memtables
        self._flush_wake = threading.Event()
        self._compact_wake = threading.Event()
        self._room = threading.Condition()
        self._stop = threading.Event()
        self._flush_mutex = threading.Lock()         # swap + flush, one at a time, in memtable order
        self._compact_mutex = threading.Lock()       # pick + run: two runners must never take one job
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self._threads = [threading.Thread(target=self._flush_loop, name="flush", daemon=True),
                         threading.Thread(target=self._compaction_loop, name="compaction", daemon=True)]
        for t in self._threads:
            t.start()

    def wake(self) -> None:
        """Called after writes: the flush thread re-checks whether the active memtable must go."""
        self._flush_wake.set()

    def wait_for_room(self) -> None:
        """Writers call this before submitting: blocks while the active memtable is full AND
        max_immutable_memtables are already waiting for flush."""
        with self._room:
            while True:
                version = self._versions.current()
                if not version.active.is_full():
                    return
                self._flush_wake.set()                     # full: make sure the flush thread knows
                if len(version.immutables) < self._max_immutable:
                    return                                 # the swap will make room right away
                self._room.wait(timeout=_RECHECK_S)

    def run_until_idle(self) -> None:
        """Test/benchmark hook: flush everything, then compact until the policy returns None."""
        self._flush_if(lambda v: v.active.max_seq > 0)
        while self._compact_one():
            pass

    def stop(self) -> None:
        self._stop.set()
        self._flush_wake.set()
        self._compact_wake.set()
        for t in self._threads:
            t.join()
        self._threads = []

    def _flush_loop(self) -> None:
        while not self._stop.is_set():
            self._flush_wake.wait(timeout=_RECHECK_S)
            self._flush_wake.clear()
            if not self._stop.is_set():
                self._flush_if(self._should_flush)

    def _compaction_loop(self) -> None:
        while not self._stop.is_set():
            self._compact_wake.wait(timeout=_RECHECK_S)
            self._compact_wake.clear()
            while not self._stop.is_set() and self._compact_one():
                pass

    def _compact_one(self) -> bool:
        """Pick and run under one lock: run_until_idle and the compaction thread could otherwise both
        pick the same job, and the second would read inputs the first already deleted."""
        with self._compact_mutex:
            job = self._policy.pick(self._versions.current())
            if job is None:
                return False
            self._compactor.run(job)
            return True

    def _should_flush(self, version) -> bool:
        """Full, OR its oldest window is closed (data time): old data must not live only in RAM + WAL.
        Newest data time = max(this memtable, already flushed): a memtable of only late points
        must still be flushed."""
        active = version.active
        if active.is_full():
            return True
        if active.min_timestamp is None:
            return False
        oldest = TimeWindow.containing(active.min_timestamp, self._smallest_window_ms)
        newest = max(active.max_timestamp, version.newest_data_ts)
        return oldest.is_closed(newest, grace_ms=self._smallest_window_ms)

    def _flush_if(self, needed) -> None:
        """Re-check under the lock: another runner may have flushed while we waited. Swap and flush
        stay together so memtables reach disk in swap order (flush relies on it, design-qa #44)."""
        with self._flush_mutex:
            if not needed(self._versions.current()):
                return
            frozen = self._flusher.swap_memtable()
            self._flusher.flush(frozen)
        with self._room:
            self._room.notify_all()
        self._compact_wake.set()


_RECHECK_S = 0.5        # also re-check without a wake, so window closing is noticed on idle shards
