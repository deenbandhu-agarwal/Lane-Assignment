"""Benchmark: `uv run python bench/run.py [--seconds 5] [--out bench/results.md]`

Measures, on this machine, with real fsync:
  1. write throughput in-process (engine only): 8 writer threads, 100-point batches,
     wal_count 1 / 2 / 4 -> points/s, batch latency p50/p99, points per fsync (group commit)
  2. the same write load over HTTP (uvicorn child process, wal_count 1): what a client sees
  3. read latency after data is flushed and compacted: 1 series raw (1 h), avg over 100 series
  4. Bloom filter false-positive rate (target 1 %)
Numbers depend on the disk (fsync cost) and core count; the report prints both.
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

from tsdb.bootstrap import build_database
from tsdb.config import EngineConfig
from tsdb.model import Aggregation, SeriesKey
from tsdb.sstable.bloom import BloomFilterFactory
from tsdb.storage.fileio import OsFileOps

T = 1_730_368_800_000
SERIES = [SeriesKey.of("cpu", {"host": f"h{i}", "region": ("us-east", "us-west", "eu")[i % 3]})
          for i in range(1_000)]
WRITERS = 8
BATCH = 100


class CountingFiles(OsFileOps):
    def __init__(self):
        self.fsyncs = 0
        self._lock = threading.Lock()

    def fsync(self, fd):
        with self._lock:
            self.fsyncs += 1
        super().fsync(fd)


def batches(writer: int):
    """Writer w owns series w, w+8, ...; time moves 1 s per batch for each series."""
    mine = SERIES[writer::WRITERS]
    i = 0
    while True:
        yield [(mine[(i * BATCH + j) % len(mine)], T + (i * BATCH + j) // len(mine) * 1_000, random.random())
               for j in range(BATCH)]
        i += 1


def run_writers(send, seconds: float) -> tuple[int, list[float]]:
    stop, latencies, counts = threading.Event(), [], [0] * WRITERS

    def writer(w):
        for batch in batches(w):
            if stop.is_set():
                return
            start = time.perf_counter()
            send(batch)
            latencies.append(time.perf_counter() - start)
            counts[w] += len(batch)

    threads = [threading.Thread(target=writer, args=(w,)) for w in range(WRITERS)]
    for t in threads:
        t.start()
    time.sleep(seconds)
    stop.set()
    for t in threads:
        t.join()
    return sum(counts), latencies


def pct(values: list[float], p: float) -> float:
    return statistics.quantiles(values, n=100)[p - 1] * 1000 if len(values) > 1 else 0.0


def bench_engine(seconds: float) -> list[dict]:
    rows = []
    for wal_count in (1, 2, 4):
        with tempfile.TemporaryDirectory() as d:
            files = CountingFiles()
            db = build_database(EngineConfig(data_dir=Path(d), wal_count=wal_count), files=files)
            db.write([(k, T, 0.0) for k in SERIES])                     # create series outside the timing
            files.fsyncs = 0
            points, lat = run_writers(db.write, seconds)
            fsyncs = files.fsyncs
            db.close()
        rows.append({"wal_count": wal_count, "points_s": points / seconds, "p50": pct(lat, 50),
                     "p99": pct(lat, 99), "per_fsync": points / max(fsyncs, 1)})
    return rows


def bench_http(seconds: float) -> dict:
    with tempfile.TemporaryDirectory() as d:
        port = 18_000 + random.randrange(1_000)
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
            local = threading.local()

            def send(batch):
                if not hasattr(local, "client"):
                    local.client = httpx.Client()            # one keep-alive connection per thread
                r = local.client.post(url + "/write", json=[
                    {"metric": k.metric, "tags": dict(k.tags), "timestamp": ts, "value": v} for k, ts, v in batch])
                r.raise_for_status()

            points, lat = run_writers(send, seconds)
        finally:
            proc.terminate()
            proc.wait()
    return {"points_s": points / seconds, "p50": pct(lat, 50), "p99": pct(lat, 99)}


def bench_reads() -> dict:
    with tempfile.TemporaryDirectory() as d:
        db = build_database(EngineConfig(data_dir=Path(d)))
        hours = 6
        for second in range(0, hours * 3600, 10):                   # 1,000 series x 1 point / 10 s x 6 h
            db.write([(k, T + second * 1000, random.random()) for k in SERIES])
        db.run_maintenance_until_idle()
        total = len(SERIES) * hours * 360

        def timed(fn, n=30):
            out = []
            for _ in range(n):
                start = time.perf_counter()
                result = fn()
                out.append(time.perf_counter() - start)
            return statistics.median(out) * 1000, result.stats

        one = timed(lambda: db.query("cpu", "host=h7", T + 3600_000, T + 7200_000 - 1, None, None))
        many = timed(lambda: db.query("cpu", "region=eu AND host!=h0", T, T + 3600_000 - 1,
                                      Aggregation.AVG, 300_000), n=5)
        db.close()
    return {"points": total, "one_ms": one[0], "one_stats": one[1], "many_ms": many[0], "many_stats": many[1]}


def bench_bloom() -> float:
    bloom = BloomFilterFactory().new(10_000, 0.01)
    for i in range(10_000):
        bloom.add(i)
    absent = range(1_000_000, 1_100_000)
    return sum(bloom.may_contain(i) for i in absent) / len(absent)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=5)
    ap.add_argument("--out", default="bench/results.md")
    args = ap.parse_args()
    random.seed(1)

    engine = bench_engine(args.seconds)
    http = bench_http(args.seconds)
    reads = bench_reads()
    fp = bench_bloom()

    gil = sys._is_gil_enabled() if hasattr(sys, "_is_gil_enabled") else True
    lines = [
        "# Benchmark results",
        "",
        f"Machine: {platform.machine()}, {os.cpu_count()} cores, {platform.system()} {platform.release()}; "
        f"Python {platform.python_version()} (GIL {'on' if gil else 'off'}). "
        f"{WRITERS} writer threads, {BATCH}-point batches, {args.seconds:g} s per run, fsync on.",
        "",
        "## Writes, engine in-process",
        "",
        "| WALs | points/s | batch p50 ms | batch p99 ms | points per fsync |",
        "|---:|---:|---:|---:|---:|",
        *[f"| {r['wal_count']} | {r['points_s']:,.0f} | {r['p50']:.1f} | {r['p99']:.1f} | {r['per_fsync']:,.0f} |"
          for r in engine],
        "",
        "## Writes over HTTP (1 WAL, JSON, one client per writer thread)",
        "",
        "| points/s | batch p50 ms | batch p99 ms |",
        "|---:|---:|---:|",
        f"| {http['points_s']:,.0f} | {http['p50']:.1f} | {http['p99']:.1f} |",
        "",
        f"## Reads ({reads['points']:,} points: 1,000 series x 6 h at 10 s, flushed and compacted)",
        "",
        "| query | median ms | tables in range | skipped by time | skipped by Bloom | blocks read |",
        "|---|---:|---:|---:|---:|---:|",
        *[f"| {name} | {ms:.1f} | {s['tables_in_range']} | {s['tables_skipped_by_time']} | "
          f"{s['tables_skipped_by_filter']} | {s['blocks_read']} |"
          for name, ms, s in (("1 series, raw, 1 h", reads["one_ms"], reads["one_stats"]),
                              ("333 series, avg 5m, 1 h", reads["many_ms"], reads["many_stats"]))],
        "",
        "## Bloom filter",
        "",
        f"10,000 ids, target 1 %: measured false-positive rate **{fp:.3%}** over 100,000 absent ids.",
        "",
    ]
    Path(args.out).write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
