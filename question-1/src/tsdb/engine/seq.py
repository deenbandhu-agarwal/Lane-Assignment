"""The shard's sequence counter: a logical clock. Every PUT and DELETE gets the next number.

Thread-safe (explicit lock: correct on free-threaded Python too). `observe` implements the Lamport
rule (counter = max(counter, seen)) used by recovery and, later, by moving series between shards.
"""

from __future__ import annotations

import threading

from tsdb.model import Seq


class SequenceCounter:
    def __init__(self, last: Seq = 0) -> None:
        self._last = last
        self._lock = threading.Lock()

    def next_block(self, n: int) -> Seq:
        """Reserve n consecutive numbers; return the first."""
        raise NotImplementedError

    def observe(self, seen: Seq) -> None:
        raise NotImplementedError

    @property
    def last(self) -> Seq:
        """Highest number handed out = the snapshot seq for a new query."""
        raise NotImplementedError
