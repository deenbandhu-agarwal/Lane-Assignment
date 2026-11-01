"""Composition root: the ONLY place that chooses concrete classes and wires them together.

Everything else receives its collaborators through its constructor and depends on tsdb.ports.
To swap an implementation, change it here (or add a registry entry + config value):

    ORDERED_STORES["rbtree"] = lambda rng, cfg: RedBlackTree()       # skip list -> RB tree
    COMPACTION_POLICIES["leveled"] = lambda cfg: LeveledPolicy(...)   # another strategy
    shard router -> ConsistentHashRouter(...)                         # multi-node later

Tests call `build_database(config, files=FailingFsyncOps(), faults=...)` to inject fakes.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping

from tsdb.compaction.policy import CompactionPolicy, TimeWindowPolicy
from tsdb.config import EngineConfig
from tsdb.engine.database import Database
from tsdb.engine.shard import Shard
from tsdb.memtable.skiplist import SkipList
from tsdb.ports import FaultInjector, FileOps, MemtableFactory, OrderedStore
from tsdb.storage.layout import ShardLayout

OrderedStoreFactory = Callable[[random.Random, EngineConfig], OrderedStore]

# Registries: name in config -> factory. Adding an implementation = adding an entry.
ORDERED_STORES: Mapping[str, OrderedStoreFactory] = {
    "skiplist": lambda rng, cfg: SkipList(rng, cfg.skiplist_max_level, cfg.skiplist_p),
}
COMPACTION_POLICIES: Mapping[str, Callable[[EngineConfig], CompactionPolicy]] = {
    "time_window": lambda cfg: TimeWindowPolicy(cfg.window_steps_ms, cfg.window_merge_threshold,
                                                cfg.late_merge_ratio, cfg.late_merge_interval_ms),
}


def memtable_factory(config: EngineConfig) -> MemtableFactory:
    """Returns a zero-arg factory producing Memtable(ORDERED_STORES[config.memtable_structure](...))."""
    raise NotImplementedError


def build_shard(config: EngineConfig, layout: ShardLayout, files: FileOps, faults: FaultInjector) -> Shard:
    """Wire one shard, in dependency order:
        InvertedIndex -> SeriesCatalog(on_new_series=index.add)
        ManifestStore, SSTableFactory(BloomFilterFactory)
        Recovery(...).run() -> RecoveredState
        SequenceCounter(last_seq), SwapLock() -> WalWriters(seq, swap_lock) -> WalSet(HashWalRouter)
        VersionSet(initial Version) -> Flusher(swap_lock, smallest window), Compactor,
        COMPACTION_POLICIES[config.compaction_policy](config)
            -> BackgroundWorker(max_immutable_memtables): flush thread + compaction thread
        executor factory (snapshot -> QueryExecutor(AGGREGATORS, limits))
        Shard(...)
    """
    raise NotImplementedError


def build_database(config: EngineConfig, files: FileOps | None = None,
                   faults: FaultInjector | None = None) -> Database:
    """Defaults: OsFileOps, EnvFaults.from_env() (NoFaults unless TSDB_CRASH_AT is set),
    SingleShardRouter, filter.parse."""
    raise NotImplementedError
