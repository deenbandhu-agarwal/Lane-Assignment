"""tsdb: a single-node embedded time-series database built on an LSM tree.

Package map (top to bottom = request to disk):

    api/         REST layer (FastAPI). Validation + HTTP status codes only.
    engine/      Database (facade) -> Shard (one LSM instance) + snapshots, flush, recovery.
    query/       Filter language, merge-on-read, aggregation, query execution.
    catalog/     Series catalog (key <-> id, series.log) and tag inverted index.
    wal/         Write-ahead log: record framing, segments, group-commit writers, N-WAL routing.
    memtable/    Skip list (from scratch) + memtable (points + range tombstones).
    sstable/     On-disk table format: writer, reader, Bloom filter.
    compaction/  Compaction policy + compactor.
    storage/     File helpers (fsync, atomic rename), MANIFEST, data-dir layout.
    faults.py    Named crash points for fault-injection tests.
"""

__version__ = "0.1.0"
