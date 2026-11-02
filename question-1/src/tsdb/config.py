"""Engine settings. One frozen object, passed down explicitly (no globals)."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EngineConfig:
    data_dir: Path

    # implementations (names looked up in tsdb.bootstrap registries)
    memtable_structure: str = "skiplist"
    compaction_policy: str = "time_window"

    # memtable
    memtable_max_bytes: int = 64 * 1024 * 1024
    memtable_entry_bytes: int = 100        # size estimate per entry (Python objects are not bytes)
    memtable_max_entries: int = 2_000_000  # hard cap, whichever comes first
    max_immutable_memtables: int = 1      # frozen memtables waiting for flush before writers wait
    skiplist_max_level: int = 12          # 4**12 ~ 16.7M entries, far above one memtable
    skiplist_p: float = 0.25              # chance to promote a node one level up
    skiplist_seed: int | None = None      # fixed in tests for repeatable shapes

    # sstable
    block_target_bytes: int = 4096
    bloom_false_positive_rate: float = 0.01

    # compaction: size-tiered inside growing time windows
    window_steps_ms: tuple[int, ...] = (3_600_000, 21_600_000, 86_400_000)   # 1 h -> 6 h -> 1 day
    window_merge_threshold: int = 4          # merge a window's files when it has this many
    late_merge_ratio: float = 0.10           # merge late files into a big window at 10% of its size...
    late_merge_interval_ms: int = 86_400_000 # ...or once per day: NOT BUILT yet (README, known gaps)

    # query limits (guard memory; exceeded -> 400)
    max_query_series: int = 10_000
    max_query_points: int = 5_000_000

    @staticmethod
    def from_env() -> "EngineConfig":
        """Every field can be set as TSDB_<FIELD NAME> (TSDB_DATA_DIR, TSDB_WAL_COUNT, ...);
        tuples are comma separated. Unset fields keep their defaults; data_dir defaults to ./data."""
        values: dict[str, object] = {"data_dir": Path("data")}
        for f in fields(EngineConfig):
            text = os.environ.get(f"TSDB_{f.name.upper()}")
            if text is None:
                continue
            try:
                values[f.name] = _parse(f.name, text)
            except ValueError as e:
                raise ValueError(f"TSDB_{f.name.upper()}={text!r}: {e}") from None
        return EngineConfig(**values)


_TYPES = {name: hint for name, hint in EngineConfig.__annotations__.items()}


def _parse(name: str, text: str) -> object:
    hint = _TYPES[name]
    if hint == "Path":
        return Path(text)
    if hint == "bool":
        if text.lower() not in ("1", "0", "true", "false"):
            raise ValueError("use true or false")
        return text.lower() in ("1", "true")
    if hint.startswith("tuple"):
        return tuple(int(part) for part in text.split(","))
    if hint.startswith("int"):
        return None if hint.endswith("None") and text == "" else int(text)
    if hint == "float":
        return float(text)
    return text
