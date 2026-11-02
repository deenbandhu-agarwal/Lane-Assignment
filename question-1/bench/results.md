# Benchmark results

Machine: arm64, 10 cores, Darwin 25.4.0; Python 3.14.5 (GIL off). 8 writer threads, 100-point batches, 5 s per run, fsync on.

## Writes, engine in-process

| points/s | batch p50 ms | batch p99 ms | points per fsync |
|---:|---:|---:|---:|
| 74,560 | 10.6 | 26.8 | 400 |

## Writes over HTTP (JSON, one client per writer thread)

| points/s | batch p50 ms | batch p99 ms |
|---:|---:|---:|
| 81,920 | 9.7 | 22.1 |

## Reads (2,160,000 points: 1,000 series x 6 h at 10 s, flushed and compacted)

| query | median ms | tables in range | skipped by time | skipped by Bloom | blocks read |
|---|---:|---:|---:|---:|---:|
| 1 series, raw, 1 h | 0.8 | 1 | 6 | 0 | 4 |
| 333 series, avg 5m, 1 h | 129.5 | 1 | 6 | 0 | 1142 |

## Bloom filter

10,000 ids, target 1 %: measured false-positive rate **1.001%** over 100,000 absent ids.
