"""No torn reads: one batch = one WAL group = applied as one unit, so a query sees all of a batch
or none of it, while flushes and compactions swap memtables and files underneath."""

import threading
import time

import pytest

from tsdb.bootstrap import build_database
from tsdb.config import EngineConfig
from tsdb.model import SeriesKey

pytestmark = pytest.mark.stress

T = 1_730_368_800_000
SENSORS = [SeriesKey.of("load", {"sensor": str(i)}) for i in range(10)]


def test_no_torn_reads_during_writes_and_compaction(tmp_path):
    db = build_database(EngineConfig(data_dir=tmp_path, memtable_max_entries=200,
                                     window_steps_ms=(1_000, 2_000, 4_000), window_merge_threshold=2))
    stop, problems, batches, reads = threading.Event(), [], [0], [0]

    def writer():
        i = 0
        while not stop.is_set():
            db.write([(k, T + i * 100, float(i)) for k in SENSORS])        # batch i: ts_i on all 10
            if i >= 3 and i % 7 == 0:
                db.write([(k, T + (i - 3) * 100, float(i - 3)) for k in SENSORS])   # overwrite, same value
            i += 1
            batches[0] = i

    def reader():
        while not stop.is_set():
            result = db.query("load", None, 0, 2**62, None, None)
            seen = {}
            for s in result.series:
                for ts, v in s.points:
                    seen.setdefault(ts, []).append(v)
            for ts, values in seen.items():
                if len(values) != len(SENSORS) or len(set(values)) != 1:
                    problems.append((ts, values))
            reads[0] += 1

    threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(3)
    stop.set()
    for t in threads:
        t.join()
    try:
        assert not problems, f"torn reads, e.g. {problems[:3]}"
        assert batches[0] > 100 and reads[0] > 10, (batches, reads)
        db.run_maintenance_until_idle()
        assert len(db.query("load", None, 0, 2**62, None, None).series[0].points) == batches[0]
    finally:
        db.close()
