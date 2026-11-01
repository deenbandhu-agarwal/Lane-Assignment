"""Engine settings. One frozen object, passed down explicitly (no globals)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EngineConfig:
    data_dir: Path

    # implementations (names looked up in tsdb.bootstrap registries)
    memtable_structure: str = "skiplist"
    compaction_policy: str = "size_tiered"

    # memtable
    memtable_max_bytes: int = 64 * 1024 * 1024
    skiplist_max_level: int = 12          # 4**12 ~ 16.7M entries, far above one memtable
    skiplist_p: float = 0.25              # chance to promote a node one level up
    skiplist_seed: int | None = None      # fixed in tests for repeatable shapes

    # sstable
    block_target_bytes: int = 4096
    bloom_false_positive_rate: float = 0.01

    # wal
    wal_count: int = 1                    # N WAL files; series -> WAL by stable hash % N
    fsync: bool = True                    # False only for the memtable-only benchmark

    # compaction / tombstones
    tombstone_compact_bytes: int = 1024 * 1024   # compact a file early above this

    # query limits (guard memory; exceeded -> 400)
    max_query_series: int = 10_000
    max_query_points: int = 5_000_000

    @staticmethod
    def from_env() -> "EngineConfig":
        """Build from TSDB_* environment variables (TSDB_DATA_DIR, TSDB_WAL_COUNT, ...)."""
        raise NotImplementedError
