"""Crash harness: a real server in a child process, a client that remembers what was confirmed,
and an oracle that says which answers are allowed after a restart.

Rule checked after every crash, per (series, timestamp):
    value after restart  in  { model WITHOUT the in-flight requests,  model WITH them }
A confirmed (200) write must be there; an in-flight one may or may not be; nothing else may appear.
Each client thread owns its own series, so its one in-flight request cannot mix with another's.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from tsdb.faults import NoFaults
from tsdb.storage.fileio import OsFileOps
from tsdb.storage.layout import ShardLayout
from tsdb.storage.manifest import ManifestStore

T = 1_730_368_800_000
METRIC = "temperature"
SMALL_ENGINE = {                         # tiny memtables and 1/2/4-minute windows: every crash point is reached fast
    "TSDB_MEMTABLE_MAX_ENTRIES": "40",
    "TSDB_WINDOW_STEPS_MS": "60000,120000,240000",
    "TSDB_WINDOW_MERGE_THRESHOLD": "2",
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, data_dir: Path, crash_at: str | None = None, crash_after: int = 1):
        self.port = free_port()
        self.log = data_dir.parent / f"server-{self.port}.log"
        env = {**os.environ, **SMALL_ENGINE, "TSDB_DATA_DIR": str(data_dir), "TSDB_PORT": str(self.port),
               "TSDB_HOST": "127.0.0.1"}
        env.pop("TSDB_CRASH_AT", None)
        if crash_at:
            env |= {"TSDB_CRASH_AT": crash_at, "TSDB_CRASH_AFTER": str(crash_after)}
        with open(self.log, "wb") as out:
            self.proc = subprocess.Popen([sys.executable, "-m", "tsdb"], env=env, stdout=out, stderr=out)
        self.url = f"http://127.0.0.1:{self.port}"
        self._wait_ready()

    def _wait_ready(self, timeout: float = 30) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited {self.proc.returncode}:\n{self.log.read_text()}")
            try:
                if httpx.get(self.url + "/series", timeout=1).status_code == 200:
                    return
            except httpx.TransportError:
                time.sleep(0.05)
        raise RuntimeError("server did not start")

    def kill9(self) -> None:
        self.proc.send_signal(signal.SIGKILL)
        self.proc.wait()

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=30)

    def killed_by_sigkill(self, timeout: float = 30) -> bool:
        try:
            return self.proc.wait(timeout=timeout) == -signal.SIGKILL
        except subprocess.TimeoutExpired:
            return False


class Model:
    """What the database must hold: (city, ts) -> value. Confirmed ops, plus the one in flight."""

    def __init__(self) -> None:
        self.confirmed: dict[tuple[str, int], float] = {}
        self.in_flight: list = []

    @staticmethod
    def apply(state: dict, op) -> None:
        if op[0] == "write":
            for city, ts, value in op[1]:
                state[(city, ts)] = value
        else:
            _, city, from_ts, to_ts = op
            for key in [k for k in state if k[0] == city and from_ts <= k[1] <= to_ts]:
                del state[key]

    def confirm(self, op) -> None:
        self.apply(self.confirmed, op)

    def allowed(self) -> tuple[dict, dict]:
        with_in_flight = dict(self.confirmed)
        for op in self.in_flight:
            self.apply(with_in_flight, op)
        return self.confirmed, with_in_flight


class Client:
    """Sends one op at a time; 200 -> confirmed, no answer -> in flight (and stop: the server is gone)."""

    def __init__(self, url: str, model: Model) -> None:
        self._http = httpx.Client(base_url=url, timeout=30)
        self.model = model

    def send(self, op) -> bool:
        self.model.in_flight = [op]
        try:
            if op[0] == "write":
                r = self._http.post("/write", json=[
                    {"metric": METRIC, "tags": {"city": c}, "timestamp": ts, "value": v} for c, ts, v in op[1]])
            else:
                _, city, from_ts, to_ts = op
                r = self._http.delete("/series", params={"metric": METRIC, "filter": f"city={city}",
                                                         "from": from_ts, "to": to_ts})
        except httpx.TransportError:
            return False
        if r.status_code != 200:
            return False                    # e.g. 500 after a failed background thread: also "maybe"
        self.model.in_flight = []
        self.model.confirm(op)
        return True


def workload(cities: list[str], steps: int, seed: int):
    """Writes moving forward in time (1 s per step: windows close, compaction moves up),
    overwrites of recent points, and range deletes. Deterministic for a seed."""
    import random
    rng = random.Random(seed)
    for i in range(steps):
        ts = T + i * 1_000
        batch = [(c, ts, round(rng.uniform(10, 40), 2)) for c in cities]
        if i >= 3:
            batch.append((rng.choice(cities), ts - 3_000, round(rng.uniform(10, 40), 2)))   # overwrite
        yield ("write", batch)
        if i % 25 == 24:
            yield ("delete", rng.choice(cities), ts - 20_000, ts - 10_000)


def read_all(url: str) -> dict[tuple[str, int], float]:
    r = httpx.get(url + "/query", params={"metric": METRIC, "from": 0, "to": 2**62}, timeout=30)
    r.raise_for_status()
    return {(s["tags"]["city"], ts): v for s in r.json()["series"] for ts, v in s["points"]}


def check(actual: dict, model: Model) -> None:
    without, with_ = model.allowed()
    wrong = {k: (actual.get(k), without.get(k), with_.get(k))
             for k in set(actual) | set(without) | set(with_)
             if actual.get(k) not in (without.get(k), with_.get(k))}
    assert not wrong, f"{len(wrong)} wrong keys, e.g. (actual, confirmed, with in-flight): {list(wrong.items())[:5]}"


def check_files(data_dir: Path) -> None:
    """After a clean stop of the recovered server: no .tmp files; every table on disk is listed in the MANIFEST and vice versa."""
    shard = ShardLayout(data_dir / "shard-0")
    state = ManifestStore(shard.manifest, OsFileOps(), NoFaults()).load()
    listed = {shard.sstable(w, int(n[:6])) for w, names in state.windows for n in names} if state else set()
    on_disk = set((shard.root / "sst").rglob("*.sst")) if (shard.root / "sst").exists() else set()
    assert not list(data_dir.rglob("*.tmp")), "a .tmp file survived recovery"
    assert on_disk == listed, f"unlisted {on_disk - listed}, missing {listed - on_disk}"
