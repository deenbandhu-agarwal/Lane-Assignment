"""Shared/exclusive lock between WAL writers and the memtable swap (design-qa #45, D2).

    WAL writer : shared     from "take seq" until "applied to memtable"  (many writers together)
    swap       : exclusive  freeze memtable + new memtable + rotate every WAL

The swap waits only for groups already in flight (about one fsync), and no new group starts while
it runs. Result: every seq in the new memtable is bigger than every seq in the frozen one, which
is the fact Rule 2 relies on (design-qa #43). Writer-preferring: a waiting swap blocks new shared
holders, so a busy write load cannot starve the flush.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class SwapLock:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._shared = 0
        self._exclusive_waiting = 0
        self._exclusive = False

    @contextmanager
    def shared(self) -> Iterator[None]:
        raise NotImplementedError
        yield

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        raise NotImplementedError
        yield
