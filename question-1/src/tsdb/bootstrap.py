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
import threading
from collections.abc import Callable, Mapping

from tsdb.catalog.inverted_index import InvertedIndex
from tsdb.catalog.series_catalog import SeriesCatalog
from tsdb.compaction.compactor import Compactor
from tsdb.compaction.policy import CompactionPolicy, TimeWindowPolicy
from tsdb.config import EngineConfig
from tsdb.engine.background import BackgroundWorker
from tsdb.engine.database import Database
from tsdb.engine.flush import Flusher
from tsdb.engine.recovery import Recovery
from tsdb.engine.routing import SingleShardRouter
from tsdb.engine.seq import SequenceCounter
from tsdb.engine.shard import Shard
from tsdb.engine.state import LiveState
from tsdb.engine.version import Version, VersionSet
from tsdb.faults import EnvFaults
from tsdb.memtable.memtable import Memtable
from tsdb.memtable.skiplist import SkipList
from tsdb.ports import FaultInjector, FileOps, MemtableFactory, OrderedStore, TableReader
from tsdb.query.aggregate import AGGREGATORS
from tsdb.query.executor import QueryExecutor
from tsdb.query.filter import parse
from tsdb.sstable.bloom import BloomFilterFactory
from tsdb.sstable.factory import SSTableFactory
from tsdb.storage.fileio import OsFileOps
from tsdb.storage.layout import ShardLayout
from tsdb.storage.manifest import ManifestStore
from tsdb.wal.wal import Wal, WalReplayer, new_segment
from tsdb.wal.writer import WalWriter

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
    """Zero-arg factory producing Memtable(ORDERED_STORES[config.memtable_structure](...))."""
    rng = random.Random(config.skiplist_seed)
    new_store = ORDERED_STORES[config.memtable_structure]
    return lambda: Memtable(new_store(rng, config), config.memtable_max_bytes,
                            config.memtable_entry_bytes, config.memtable_max_entries)


def build_shard(config: EngineConfig, layout: ShardLayout, files: FileOps, faults: FaultInjector) -> Shard:
    """Wire one shard, in dependency order (recovery first: everything else starts from its result).
    The returned shard is running: WAL writer threads and the two background threads are started."""
    files.make_dirs(layout.wal_segment(0).parent)
    index = InvertedIndex()
    catalog = SeriesCatalog(layout.series_log, files, on_new_series=index.add)
    manifest = ManifestStore(layout.manifest, files, faults)
    tables = SSTableFactory(layout.sstable, files, faults, BloomFilterFactory(),
                            config.block_target_bytes, config.bloom_false_positive_rate)
    new_memtable = memtable_factory(config)
    recovered = Recovery(layout, manifest, catalog, tables, WalReplayer(files, layout.wal_segment).replay,
                         new_memtable, files).run()

    seq = SequenceCounter(recovered.last_seq)
    swap_lock = threading.Lock()          # WAL group commit vs memtable swap (design-qa #45 D2)
    writer = WalWriter(new_segment(layout.wal_segment(recovered.active_segment), files), seq, swap_lock,
                       recovered.memtable.apply, before_fsync=catalog.sync, faults=faults)
    wal = Wal(writer, layout.wal_segment, files)

    def on_obsolete(table: TableReader) -> None:
        table.close()
        files.remove(layout.sstable(table.window, int(table.name[:6])))

    versions = VersionSet(Version(0, recovered.memtable, (), recovered.windows,
                                  recovered.manifest.newest_data_ts), on_obsolete)
    state = LiveState(manifest, versions, recovered.manifest, recovered.active_segment)
    smallest = config.window_steps_ms[0]
    background = BackgroundWorker(
        versions, Flusher(versions, wal, state, tables, new_memtable, files, faults, swap_lock, smallest),
        Compactor(versions, state, tables, faults), COMPACTION_POLICIES[config.compaction_policy](config),
        config.max_immutable_memtables, smallest)
    new_executor = lambda snapshot: QueryExecutor(snapshot, catalog, AGGREGATORS,
                                                  config.max_query_series, config.max_query_points)
    writer.start()
    background.start()
    return Shard(catalog, index, wal, versions, seq, background, new_executor)


def build_database(config: EngineConfig, files: FileOps | None = None,
                   faults: FaultInjector | None = None) -> Database:
    """Defaults: OsFileOps, EnvFaults.from_env() (NoFaults unless TSDB_CRASH_AT is set),
    SingleShardRouter, filter.parse."""
    files = files or OsFileOps()
    faults = faults or EnvFaults.from_env()
    router = SingleShardRouter()
    shards = [build_shard(config, ShardLayout(config.data_dir / f"shard-{i}"), files, faults)
              for i in router.all_shards()]
    return Database(shards, router, parse)
