"""Benchmarks (raw output -> bench/results/, committed):

  1. memtable insert throughput, 1 core, no WAL        (brief target >= 100,000 writes/s)
  2. end-to-end write throughput with WAL + fsync, N = 1, 2, 4 WALs
  3. query latency p50 / p95 / p99: single series, many series (weak spot), aggregations
  4. Bloom filter measured false-positive rate under load
Regenerate: make bench
"""

from __future__ import annotations


def main() -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
