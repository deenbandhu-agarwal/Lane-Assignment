# Benchmark results

Machine: aarch64, 10 cores, Linux 7.0.5-orbstack-00330-ge3df4e19b0a0-dirty; Python 3.14.5 (GIL off). Seed 42. Regenerate: `uv run python bench/run.py` (or `docker compose run --rm bench`). Total run time 121 s.

## 1. Memtable inserts, 1 thread (10,000,000 points, 10,000 series)

| points/s | seconds | memtable size |
|---:|---:|---:|
| 320,557 | 31.2 | 671,088 entries, then a new one |

## 2. Full load end to end, in-process (10,000,000 points, 10,000 series)

8 writer threads, 100-point batches, WAL with group commit, fsync before every reply; flush and compaction run at the same time.

| points/s | batch p50 ms | batch p99 ms | points per fsync | flush + compact after load | tables at the end |
|---:|---:|---:|---:|---:|---:|
| 132,800 | 5.4 | 15.9 | 398 | 1.0 s | 8 |

## 3. Queries on that data (after flush + compaction)

| query | runs | series in answer | p50 ms | p95 ms | p99 ms | tables in range | skipped by time | skipped by Bloom | blocks read |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 series, raw, 1 h | 200 | 1 | 2.3 | 2.7 | 3.1 | 3 | 5 | 0 | 5 |
| 1 series, count, all time | 200 | 1 | 5.4 | 6.5 | 11.3 | 8 | 0 | 0 | 13 |
| 10 series (OR), max 1m, 1 h | 100 | 10 | 8.5 | 16.6 | 28.2 | 3 | 5 | 0 | 54 |
| ~500 series (AND, !=), avg 5m, 1 h | 20 | 499 | 227.2 | 336.3 | 370.0 | 3 | 5 | 0 | 2615 |

## 4. Writes over HTTP (5 s, JSON, one keep-alive client per writer thread)

| points/s | batch p50 ms | batch p99 ms |
|---:|---:|---:|
| 140,000 | 5.1 | 18.5 |

## 5. Bloom filter

10,000 ids, target 1 %: m = 95,856 bits, k = 7; measured false-positive rate **1.001%** over 100,000 absent ids.
