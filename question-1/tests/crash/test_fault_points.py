"""Crash at each of the 5 dangerous moments (SIGKILL from inside, TSDB_CRASH_AT), restart, check.

Each case proves: the crash point was really reached (exit by SIGKILL); after restart every
confirmed write and delete holds, the in-flight request is all-or-nothing per point, nothing else
appears; recovery leaves no .tmp or unlisted table; the restarted server takes new writes.
"""

import pytest

from tests.crash.harness import Client, Model, Server, check, check_files, read_all, workload

pytestmark = pytest.mark.crash

CITIES = ["Delhi", "Mumbai", "Pune", "Chennai"]

CASES = [                                 # (crash point, which hit): late enough that tables exist
    ("wal_append", 60),                   # bytes appended, fsync not done
    ("memtable_flush", 3),                # memtable frozen, no table yet
    ("sstable_write", 4),                 # half a .tmp table on disk
    ("manifest_update", 4),               # MANIFEST.tmp written, not renamed
    ("compaction_swap", 1),               # compaction output published, MANIFEST not switched
]


@pytest.mark.parametrize("crash_at,after", CASES, ids=[c for c, _ in CASES])
def test_crash_point(tmp_path, crash_at, after):
    data = tmp_path / "data"
    server = Server(data, crash_at, after)
    model = Model()
    client = Client(server.url, model)
    for op in workload(CITIES, steps=400, seed=7):
        if not client.send(op):
            break
    assert server.killed_by_sigkill(), f"{crash_at} #{after} was never reached:\n{server.log.read_text()}"

    again = Server(data)
    try:
        check(read_all(again.url), model)
        model.in_flight = []                                   # the restart decided; take what is there
        model.confirmed = read_all(again.url)
        assert Client(again.url, model).send(("write", [("Delhi", 1_730_368_800_000, 99.0)]))
        check(read_all(again.url), model)
    finally:
        again.stop()
    check_files(data)
