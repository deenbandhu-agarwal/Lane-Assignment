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


class BackgroundWorker:
    def __init__(self, versions: VersionSet, flusher: Flusher, compactor: Compactor,
                 policy: CompactionPolicy, max_immutable_memtables: int) -> None:
        self._versions = versions
        self._flusher = flusher
        self._compactor = compactor
        self._policy = policy
        self._max_immutable = max_immutable_memtables
        self._flush_wake = threading.Event()
        self._compact_wake = threading.Event()
        self._room = threading.Condition()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        raise NotImplementedError

    def wake(self) -> None:
        """Called when a memtable becomes full or newest data time closes a window."""
        raise NotImplementedError

    def wait_for_room(self) -> None:
        """Writers call this before submitting: blocks while the active memtable is full AND
        max_immutable_memtables are already waiting for flush."""
        raise NotImplementedError

    def run_until_idle(self) -> None:
        """Test/benchmark hook: flush everything, then compact until the policy returns None."""
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def _flush_loop(self) -> None:
        raise NotImplementedError

    def _compaction_loop(self) -> None:
        raise NotImplementedError
