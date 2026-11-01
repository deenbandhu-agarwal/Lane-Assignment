"""Which tables to compact next (OCP: a new strategy is a new CompactionPolicy; bootstrap picks it).

Decided strategy (design-qa #37-#39): size-tiered INSIDE growing time windows.
    steps            1 h -> 6 h -> 1 day (config.window_steps_ms), windows nest exactly
    size-tiered      a window with >= merge_threshold tables -> merge them into one table of that window
    move-up          a bigger window whose smaller child windows are ALL closed -> merge every table of
                     those children (+ any table already in the bigger window) into one bigger-window table
    late files       small tables inside an already moved-up window are merged into it only when they
                     reach late_merge_ratio of its size, or once per late_merge_interval (data time)
    closed           TimeWindow.is_closed(newest_data_ts, grace = smallest step)
Priority per pick(): size-tiered, then move-up (smallest first), then late files. One job at a time.

Ownership: flush always writes the SMALLEST step, so a late point for an hour that was already
moved up lands in a 1 h window INSIDE a 6 h window that has a file. Every file therefore belongs to
its TOP window: the biggest window above it (or itself) that has a file.
    size-tiered  top windows of the smallest step
    move-up      a closed window with no file whose tops are all smaller windows
    late merge   a top window with its own file(s) plus extras (late files below it, delete pieces)
Compaction never mixes windows that do not nest, so "every table inside one window" always holds.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from tsdb.engine.version import Version
from tsdb.model import TimeWindow
from tsdb.ports import TableReader


class JobKind(str, Enum):
    SIZE_TIERED = "size_tiered"
    MOVE_UP = "move_up"
    LATE_MERGE = "late_merge"


@dataclass(frozen=True, slots=True)
class CompactionJob:
    kind: JobKind
    inputs: tuple[TableReader, ...]
    output_window: TimeWindow
    # Tombstone dropping is NOT decided here: the Compactor applies Rule 2 against the Version.


class CompactionPolicy(ABC):
    @abstractmethod
    def pick(self, version: Version) -> CompactionJob | None:
        """None = nothing to do."""


class TimeWindowPolicy(CompactionPolicy):
    def __init__(self, window_steps_ms: tuple[int, ...], merge_threshold: int,
                 late_merge_ratio: float, late_merge_interval_ms: int) -> None:
        self._steps = window_steps_ms
        self._merge_threshold = merge_threshold
        self._late_merge_ratio = late_merge_ratio
        self._late_merge_interval_ms = late_merge_interval_ms

    def pick(self, version: Version) -> CompactionJob | None:
        groups = self._groups(version)
        return (self._size_tiered(groups) or self._move_up(groups, version.newest_data_ts)
                or self._late_merge(groups))

    def _groups(self, version: Version) -> dict[TimeWindow, list[tuple[TimeWindow, TableReader]]]:
        """top window -> every (window, table) it owns."""
        with_files = {w for w, tables in version.windows if tables}
        groups: dict[TimeWindow, list[tuple[TimeWindow, TableReader]]] = {}
        for window, tables in version.windows:
            top = window
            for step in self._steps:
                if step > window.size_ms and (parent := window.parent(step)) in with_files:
                    top = parent
            groups.setdefault(top, []).extend((window, t) for t in tables)
        return groups

    def _size_tiered(self, groups) -> CompactionJob | None:
        for top, members in sorted(groups.items()):
            if top.size_ms == self._steps[0] and len(members) >= self._merge_threshold:
                return CompactionJob(JobKind.SIZE_TIERED, tuple(t for _, t in members), top)
        return None

    def _move_up(self, groups, newest_data_ts: int) -> CompactionJob | None:
        return None

    def _late_merge(self, groups) -> CompactionJob | None:
        return None
