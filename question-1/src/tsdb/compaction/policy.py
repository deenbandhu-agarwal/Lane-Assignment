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
        raise NotImplementedError

    def _size_tiered(self, version: Version) -> CompactionJob | None:
        raise NotImplementedError

    def _move_up(self, version: Version) -> CompactionJob | None:
        raise NotImplementedError

    def _late_merge(self, version: Version) -> CompactionJob | None:
        raise NotImplementedError
