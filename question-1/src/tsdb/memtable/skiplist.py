"""Skip list, written from scratch (implements ports.OrderedStore).

Why a skip list (README has the full justification):
  - insert touches only neighbour pointers (no rotations) -> readers walk without a lock
  - level 0 is already a sorted linked list -> flush and range reads are a simple walk
  - ~150 lines, easy to explain live
A red-black tree would be another OrderedStore; it needs a read lock or copy-on-write because
rotations move nodes under readers. Switching = bootstrap's `ORDERED_STORES` entry + config.

Key order: (series_id asc, timestamp asc, -seq asc) -> all versions kept, newest first.
Height: start at 1, go up while rng.random() < p (p = 1/4), max 12. RNG injected (repeatable tests).
Concurrency: ONE writer at a time (memtable lock). Node built fully, then linked bottom level
first; each link is a single reference store -> readers never see a broken list.
"""

from __future__ import annotations

import random
from collections.abc import Iterator

from tsdb.ports import OrderedKey


class _Node:
    __slots__ = ("key", "value", "next")

    def __init__(self, key: OrderedKey | None, value: float, height: int) -> None:
        self.key = key
        self.value = value
        self.next: list[_Node | None] = [None] * height


class SkipList:
    def __init__(self, rng: random.Random, max_level: int = 12, p: float = 0.25) -> None:
        self._rng = rng
        self._max_level = max_level
        self._p = p
        self._head = _Node(None, 0.0, max_level)
        self._level = 1
        self._len = 0

    def insert(self, key: OrderedKey, value: float) -> None:
        """Caller guarantees ONE writer at a time and unique keys."""
        preds = self._find_predecessors(key)
        height = self._random_height()
        node = _Node(key, value, height)
        for level in range(height):                 # 1. node fully built before anyone sees it
            node.next[level] = preds[level].next[level]
        for level in range(height):                 # 2. publish bottom level first
            preds[level].next[level] = node
        self._level = max(self._level, height)
        self._len += 1

    def iter_from(self, key: OrderedKey) -> Iterator[tuple[OrderedKey, float]]:
        """Entries with key >= `key`, ascending."""
        node = self._find_predecessors(key)[0].next[0]
        while node is not None:
            yield node.key, node.value
            node = node.next[0]

    def __iter__(self) -> Iterator[tuple[OrderedKey, float]]:
        node = self._head.next[0]
        while node is not None:
            yield node.key, node.value
            node = node.next[0]

    def __len__(self) -> int:
        return self._len

    def _random_height(self) -> int:
        height = 1
        while height < self._max_level and self._rng.random() < self._p:
            height += 1
        return height

    def _find_predecessors(self, key: OrderedKey) -> list[_Node]:
        """For every level, the last node whose key < `key` (head if none)."""
        preds = [self._head] * self._max_level
        node = self._head
        for level in range(self._level - 1, -1, -1):   # levels above _level: pred is head
            nxt = node.next[level]
            while nxt is not None and nxt.key < key:
                node, nxt = nxt, nxt.next[level]
            preds[level] = node
        return preds
