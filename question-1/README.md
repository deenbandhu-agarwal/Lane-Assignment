# Question 1: Time-series database storage engine

> Status: **scaffold**. Structure and interfaces only; no implementation yet.

## Run

| What | Command |
|---|---|
| Tests (offline, one command) | `docker compose run --rm --build test` (or `make test-docker`) |
| Server on :8080 | `docker compose up --build` |
| Benchmarks (raw output → `bench/results/`) | `make bench` |
| Local dev (free-threaded Python 3.14t) | `make setup && make test` |

## Architecture
_TODO: diagram — API → Database → Shard (catalog + index, N WALs, memtable skip list, SSTables, MANIFEST)._

| Package | Responsibility |
|---|---|
| `api/` | REST, validation, status codes |
| `engine/` | `Database` facade, `Shard`, snapshots (`version.py`), flush, recovery, background work |
| `catalog/` | series key ↔ id (`series.log`), tag inverted index |
| `wal/` | record framing, segments, group-commit writer, N-WAL routing |
| `memtable/` | skip list (from scratch), memtable with versions + tombstones |
| `sstable/` | format, writer, reader (forward cursor), Bloom filter |
| `compaction/` | policy + compactor |
| `query/` | filter language, merge-on-read, aggregation, executor |
| `storage/` | fsync / atomic rename, MANIFEST, directory layout |

## Semantics (must be documented and tested)
- Same series + timestamp written twice: _TODO (last write wins by seq)_
- Delete: _TODO (range tombstones, survive compaction + restart)_
- Acknowledged write after a crash: _TODO (200 only after fdatasync; group commit)_

## On-disk format
_TODO: byte-layout diagram (see `src/tsdb/sstable/format.py`)._

## Bloom filter
_TODO: k and m for 1% FPR with the math; measured FPR under load._

## Benchmarks
_TODO: 10M points / 10K series, memtable writes/s, end-to-end writes/s (N = 1, 2, 4), query p50/p95/p99._

## Assumptions
- Runtime is free-threaded CPython 3.14t (GIL off). Code uses explicit locks and does not rely on the GIL.
