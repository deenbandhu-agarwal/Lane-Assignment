"""Benchmark: `uv run python bench/run.py [--points 10000000] [--series 10000] [--seconds 5] [--out ...]`

Seeded (random.Random(SEED) everywhere). Measures, on this machine:
  1. memtable inserts on ONE core: one thread, Memtable.apply, all --points over --series
     (a new memtable every memtable_max_entries, like a flush would do) -> points/s
  2. the full load end to end in-process: --points over --series, 8 writer threads,
     100-point batches, WAL + group commit + real fsync, flush and compaction running
  3. query latency p50/p95/p99 on that data (after flush + compaction), 4 query shapes
  4. the same write load over HTTP for --seconds (uvicorn child process): what a client sees
  5. Bloom filter false-positive rate (target 1 %)
Numbers depend on the disk (fsync) and the cores; the report prints both.
"""

from __future__ import annotations

import argparse
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

from tsdb.bootstrap import build_database, memtable_factory
from tsdb.config import EngineConfig
from tsdb.model import Aggregation, Point, SeriesKey
from tsdb.sstable.bloom import BloomFilterFactory
from tsdb.storage.fileio import OsFileOps

SEED = 42
T = 1_730_368_800_000            # 2024-10-31 10:00 UTC
STEP_MS = 10_000                 # one point per series every 10 s
WRITERS = 8
BATCH = 100
REGIONS = ("us-east", "us-west", "eu", "ap")


def make_series(n: int) -> list[SeriesKey]:
    return [SeriesKey.of("cpu", {"host": f"h{i}", "region": REGIONS[i % 4], "service": f"s{i % 10}"})
            for i in range(n)]


def load(series: list[SeriesKey], writer: int, total_points: int):
    """Writer w owns series w, w + 8, ...; it walks time forward, one point per series per step.
    Values come from a per-writer seeded RNG, so every run writes the same data."""
    rng = random.Random(SEED + writer)
    mine = series[writer::WRITERS]
    per_writer = total_points // WRITERS
    batch, n = [], 0
    while n < per_writer:
        step, k = divmod(n, len(mine))
        batch.append((mine[k], T + step * STEP_MS, round(rng.uniform(0, 100), 3)))
        n += 1
        if len(batch) == BATCH:
            yield batch
            batch = []
    if batch:
        yield batch


def pct(values: list[float], p: int) -> float:
    return statistics.quantiles(values, n=100)[p - 1] * 1000 if len(values) > 1 else values[0] * 1000


class CountingFiles(OsFileOps):
    def __init__(self):
        self.fsyncs = 0
        self._lock = threading.Lock()

    def fsync(self, fd):
        with self._lock:
            self.fsyncs += 1
        super().fsync(fd)


# ------------------------------------------------------------------------------ 1. memtable, 1 core
def bench_memtable(points: int, series: int) -> dict:
    config = EngineConfig(data_dir=Path("unused"), skiplist_seed=SEED)
    new_memtable = memtable_factory(config)
    memtable, seq, rng = new_memtable(), 0, random.Random(SEED)
    start = time.perf_counter()
    step = 0
    while seq < points:
        for first in range(0, series, 1_000):
            entries = []
            for sid in range(first, min(first + 1_000, series)):
                seq += 1
                entries.append(Point(sid, T + step * STEP_MS, seq, rng.random()))
            memtable.apply(entries)
            if memtable.is_full():
                memtable = new_memtable()          # what a flush swap does
            if seq >= points:
                break
        step += 1
    elapsed = time.perf_counter() - start
    cap = min(config.memtable_max_entries, config.memtable_max_bytes // config.memtable_entry_bytes)
    return {"points": seq, "seconds": elapsed, "points_s": seq / elapsed, "cap": cap}


# ------------------------------------------------------------------------------ 2 + 3. full load, queries
def bench_load_and_queries(points: int, series_n: int) -> dict:
    series = make_series(series_n)
    with tempfile.TemporaryDirectory() as d:
        files = CountingFiles()
        db = build_database(EngineConfig(data_dir=Path(d)), files=files)
        latencies: list[float] = []
        written = [0] * WRITERS

        def writer(w):
            for batch in load(series, w, points):
                t0 = time.perf_counter()
                db.write(batch)
                latencies.append(time.perf_counter() - t0)
                written[w] += len(batch)

        threads = [threading.Thread(target=writer, args=(w,)) for w in range(WRITERS)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        write_s = time.perf_counter() - start
        fsyncs = files.fsyncs
        t0 = time.perf_counter()
        db.run_maintenance_until_idle()
        settle_s = time.perf_counter() - t0
        tables = sum(1 for _ in Path(d).rglob("*.sst"))

        span = (points // series_n) * STEP_MS                     # data covers [T, T + span)
        hour = 3_600_000
        rng = random.Random(SEED)
        shapes = [
            ("1 series, raw, 1 h", 200,
             lambda: db.query("cpu", f"host=h{rng.randrange(series_n)}", T, T + hour - 1, None, None)),
            ("1 series, count, all time", 200,
             lambda: db.query("cpu", f"host=h{rng.randrange(series_n)}", T, T + span, Aggregation.COUNT, None)),
            ("10 series (OR), max 1m, 1 h", 100,
             lambda: db.query("cpu", " OR ".join(f"host=h{rng.randrange(series_n)}" for _ in range(10)),
                              T, T + hour - 1, Aggregation.MAX, 60_000)),
            ("~500 series (AND, !=), avg 5m, 1 h", 20,
             lambda: db.query("cpu", "region=eu AND service=s2 AND host!=h2", T, T + hour - 1,
                              Aggregation.AVG, 300_000)),
        ]
        queries = []
        for name, runs, fn in shapes:
            times, result = [], None
            for _ in range(runs):
                q0 = time.perf_counter()
                result = fn()
                times.append(time.perf_counter() - q0)
            queries.append({"name": name, "runs": runs, "series": len(result.series),
                            "p50": pct(times, 50), "p95": pct(times, 95), "p99": pct(times, 99),
                            "stats": result.stats})
        db.close()
    total = sum(written)
    return {"points": total, "write_s": write_s, "points_s": total / write_s, "per_fsync": total / max(fsyncs, 1),
            "p50": pct(latencies, 50), "p99": pct(latencies, 99), "settle_s": settle_s, "tables": tables,
            "queries": queries}


# ------------------------------------------------------------------------------ 4. HTTP
def bench_http(seconds: float, series_n: int) -> dict:
    series = make_series(series_n)
    with tempfile.TemporaryDirectory() as d:
        port = 18_000 + random.Random(SEED).randrange(1_000)
        env = {**os.environ, "TSDB_DATA_DIR": d, "TSDB_PORT": str(port), "TSDB_HOST": "127.0.0.1"}
        proc = subprocess.Popen([sys.executable, "-m", "tsdb"], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(300):
                try:
                    httpx.get(url + "/series", timeout=1)
                    break
                except httpx.TransportError:
                    time.sleep(0.05)
            stop, latencies, counts = threading.Event(), [], [0] * WRITERS

            def writer(w):
                client = httpx.Client()                    # one keep-alive connection per thread
                for batch in load(series, w, 10**9):
                    if stop.is_set():
                        return
                    body = [{"metric": k.metric, "tags": dict(k.tags), "timestamp": ts, "value": v}
                            for k, ts, v in batch]
                    t0 = time.perf_counter()
                    client.post(url + "/write", json=body).raise_for_status()
                    latencies.append(time.perf_counter() - t0)
                    counts[w] += len(batch)

            threads = [threading.Thread(target=writer, args=(w,)) for w in range(WRITERS)]
            for t in threads:
                t.start()
            time.sleep(seconds)
            stop.set()
            for t in threads:
                t.join()
        finally:
            proc.terminate()
            proc.wait()
    return {"points_s": sum(counts) / seconds, "p50": pct(latencies, 50), "p99": pct(latencies, 99)}


# ------------------------------------------------------------------------------ 5. Bloom
def bench_bloom() -> dict:
    bloom = BloomFilterFactory().new(10_000, 0.01)
    for i in range(10_000):
        bloom.add(i)
    absent = range(1_000_000, 1_100_000)
    return {"m": bloom.m_bits, "k": bloom.k, "fp": sum(bloom.may_contain(i) for i in absent) / len(absent)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", type=int, default=10_000_000)
    ap.add_argument("--series", type=int, default=10_000)
    ap.add_argument("--seconds", type=float, default=5, help="length of the HTTP run")
    ap.add_argument("--out", default="bench/results.md")
    args = ap.parse_args()

    started = time.perf_counter()
    mem = bench_memtable(args.points, args.series)
    print(f"memtable done: {mem['points_s']:,.0f} points/s", flush=True)
    full = bench_load_and_queries(args.points, args.series)
    print(f"load done: {full['points_s']:,.0f} points/s", flush=True)
    http = bench_http(args.seconds, args.series)
    bloom = bench_bloom()

    gil = sys._is_gil_enabled() if hasattr(sys, "_is_gil_enabled") else True
    lines = [
        "# Benchmark results",
        "",
        f"Machine: {platform.machine()}, {os.cpu_count()} cores, {platform.system()} {platform.release()}; "
        f"Python {platform.python_version()} (GIL {'on' if gil else 'off'}). Seed {SEED}. "
        f"Regenerate: `uv run python bench/run.py` (or `docker compose run --rm bench`). "
        f"Total run time {time.perf_counter() - started:.0f} s.",
        "",
        f"## 1. Memtable inserts, 1 thread ({mem['points']:,} points, {args.series:,} series)",
        "",
        "| points/s | seconds | memtable size |",
        "|---:|---:|---:|",
        f"| {mem['points_s']:,.0f} | {mem['seconds']:.1f} | {mem['cap']:,} entries, then a new one |",
        "",
        f"## 2. Full load end to end, in-process ({full['points']:,} points, {args.series:,} series)",
        "",
        f"{WRITERS} writer threads, {BATCH}-point batches, WAL with group commit, fsync before every reply; "
        "flush and compaction run at the same time.",
        "",
        "| points/s | batch p50 ms | batch p99 ms | points per fsync | flush + compact after load | tables at the end |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {full['points_s']:,.0f} | {full['p50']:.1f} | {full['p99']:.1f} | {full['per_fsync']:,.0f} | "
        f"{full['settle_s']:.1f} s | {full['tables']} |",
        "",
        "## 3. Queries on that data (after flush + compaction)",
        "",
        "| query | runs | series in answer | p50 ms | p95 ms | p99 ms | tables in range | skipped by time | skipped by Bloom | blocks read |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *[f"| {q['name']} | {q['runs']} | {q['series']} | {q['p50']:.1f} | {q['p95']:.1f} | {q['p99']:.1f} | "
          f"{q['stats']['tables_in_range']} | {q['stats']['tables_skipped_by_time']} | "
          f"{q['stats']['tables_skipped_by_filter']} | {q['stats']['blocks_read']} |" for q in full["queries"]],
        "",
        f"## 4. Writes over HTTP ({args.seconds:g} s, JSON, one keep-alive client per writer thread)",
        "",
        "| points/s | batch p50 ms | batch p99 ms |",
        "|---:|---:|---:|",
        f"| {http['points_s']:,.0f} | {http['p50']:.1f} | {http['p99']:.1f} |",
        "",
        "## 5. Bloom filter",
        "",
        f"10,000 ids, target 1 %: m = {bloom['m']:,} bits, k = {bloom['k']}; "
        f"measured false-positive rate **{bloom['fp']:.3%}** over 100,000 absent ids.",
        "",
    ]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
