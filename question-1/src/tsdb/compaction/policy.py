"""Which tables to compact next (OCP: new strategies are new classes; bootstrap picks one).
Strategy NOT decided yet (size-tiered / leveled / size-tiered inside growing time windows;
Q&A #21, #29). Everything else depends on the CompactionPolicy interface only."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from tsdb.engine.version import Version
from tsdb.ports import TableReader


@dataclass(frozen=True, slots=True)
class CompactionJob:
    inputs: tuple[TableReader, ...]
    output_level: int
    drop_tombstones: bool        # True only if no older data can exist below output_level


class CompactionPolicy(ABC):
    @abstractmethod
    def pick(self, version: Version) -> CompactionJob | None:
        """None = nothing to do."""


class SizeTieredPolicy(CompactionPolicy):
    def __init__(self, min_tables: int = 4) -> None:
        self._min_tables = min_tables

    def pick(self, version: Version) -> CompactionJob | None:
        raise NotImplementedError
