# Benchmark results

Machine: arm64, 10 cores, Darwin 25.4.0; Python 3.14.5 (GIL off). Seed 42. Regenerate: `uv run python bench/run.py` (or `docker compose run --rm bench`). Total run time 216 s.

## 1. Memtable inserts, 1 thread (10,000,000 points, 10,000 series)

| points/s | seconds | memtable size |
|---:|---:|---:|
| 345,258 | 29.0 | 671,088 entries, then a new one |

## 2. Full load end to end, in-process (10,000,000 points, 10,000 series)

8 writer threads, 100-point batches, WAL with group commit, fsync before every reply; flush and compaction run at the same time.

| points/s | batch p50 ms | batch p99 ms | points per fsync | flush + compact after load | tables at the end |
|---:|---:|---:|---:|---:|---:|
| 59,111 | 13.0 | 26.4 | 397 | 1.7 s | 8 |

## 3. Queries on that data (after flush + compaction)

| query | runs | series in answer | p50 ms | p95 ms | p99 ms | tables in range | skipped by time | skipped by Bloom | blocks read |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 series, raw, 1 h | 200 | 1 | 2.7 | 4.3 | 6.6 | 3 | 5 | 0 | 7 |
| 1 series, count, all time | 200 | 1 | 7.0 | 8.4 | 10.3 | 8 | 0 | 0 | 12 |
| 10 series (OR), max 1m, 1 h | 100 | 10 | 10.7 | 15.4 | 27.7 | 3 | 5 | 0 | 55 |
| ~500 series (AND, !=), avg 5m, 1 h | 20 | 499 | 325.6 | 387.2 | 397.6 | 3 | 5 | 0 | 2600 |

## 4. Writes over HTTP (5 s, JSON, one keep-alive client per writer thread)

| points/s | batch p50 ms | batch p99 ms |
|---:|---:|---:|
| 70,140 | 9.7 | 73.7 |

## 5. Bloom filter

10,000 ids, target 1 %: m = 95,856 bits, k = 7; measured false-positive rate **1.001%** over 100,000 absent ids.
