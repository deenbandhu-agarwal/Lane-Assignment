# Benchmark results

Machine: arm64, 10 cores, Darwin 25.4.0; Python 3.14.5 (GIL off). 8 writer threads, 100-point batches, 5 s per run, fsync on.

## Writes, engine in-process

| WALs | points/s | batch p50 ms | batch p99 ms | points per fsync |
|---:|---:|---:|---:|---:|
| 1 | 70,560 | 10.8 | 26.9 | 400 |
| 2 | 52,900 | 15.0 | 20.6 | 200 |
| 4 | 28,640 | 28.0 | 36.8 | 98 |

## Writes over HTTP (1 WAL, JSON, one client per writer thread)

| points/s | batch p50 ms | batch p99 ms |
|---:|---:|---:|
| 87,800 | 8.6 | 24.9 |

## Reads (2,160,000 points: 1,000 series x 6 h at 10 s, flushed and compacted)

| query | median ms | tables in range | skipped by time | skipped by Bloom | blocks read |
|---|---:|---:|---:|---:|---:|
| 1 series, raw, 1 h | 0.8 | 1 | 6 | 0 | 4 |
| 333 series, avg 5m, 1 h | 133.5 | 1 | 6 | 0 | 1142 |

## Bloom filter

10,000 ids, target 1 %: measured false-positive rate **1.001%** over 100,000 absent ids.
