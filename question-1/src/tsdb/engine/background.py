"""Background thread for flush and compaction, so writes and queries never do that work inline.
Depends on the Flusher, Compactor and CompactionPolicy it is given (no Shard).

Loop: flush when the memtable is full (estimated bytes or max entries) OR its oldest window is
closed, so old data does not live only in memory + WAL for hours; then run one compaction job if
the policy picks one."""

from __future__ import annotations

import threading

from tsdb.compaction.compactor import Compactor
from tsdb.compaction.policy import CompactionPolicy
from tsdb.engine.flush import Flusher
from tsdb.engine.version import VersionSet


class BackgroundWorker:
    def __init__(self, versions: VersionSet, flusher: Flusher, compactor: Compactor,
                 policy: CompactionPolicy) -> None:
        self._versions = versions
        self._flusher = flusher
        self._compactor = compactor
        self._policy = policy
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        raise NotImplementedError

    def wake(self) -> None:
        """Called when a memtable becomes full or a flush adds tables, or newest data time closes a window."""
        raise NotImplementedError

    def run_until_idle(self) -> None:
        """Test/benchmark hook: flush everything, then compact until the policy returns None."""
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def _run(self) -> None:
        raise NotImplementedError
