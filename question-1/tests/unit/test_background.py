"""BackgroundWorker: flush thread + compaction thread (seams B1-B4)."""

import random
import threading
import time

import pytest

from tsdb.compaction.compactor import Compactor
from tsdb.compaction.policy import TimeWindowPolicy
from tsdb.engine.background import BackgroundWorker
from tsdb.engine.flush import Flusher
from tsdb.engine.state import LiveState
from tsdb.engine.swap_lock import SwapLock
from tsdb.engine.version import Version, VersionSet
from tsdb.faults import NoFaults
from tsdb.memtable.memtable import Memtable
from tsdb.memtable.skiplist import SkipList
from tsdb.model import ManifestState, Point, TimeWindow
from tsdb.sstable.bloom import BloomFilterFactory
from tsdb.sstable.factory import SSTableFactory
from tsdb.storage.fileio import OsFileOps
from tsdb.storage.layout import ShardLayout
from tsdb.storage.manifest import ManifestStore

MINUTE = 60_000
T = 1_730_368_800_000                                  # 10:00
W_10_00 = TimeWindow(MINUTE, T)


def eventually(condition, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.005)
    return False


class FakeWal:
    def __init__(self):
        self.memtable = None

    def rotate_all(self, new_segment_no, new_memtable):
        self.memtable = new_memtable
        return []


class Engine:
    """Real flush + compaction pieces; steps 1 -> 2 -> 4 minutes, merge at 2 (as in the example)."""

    def __init__(self, tmp_path, max_entries=10**9):
        files, faults = OsFileOps(), NoFaults()
        layout = ShardLayout(tmp_path)
        new_memtable = lambda: Memtable(SkipList(random.Random(1)), 10**9, 100, max_entries)
        self.versions = VersionSet(Version(0, new_memtable(), (), (), 0), on_obsolete=lambda t: None)
        tables = SSTableFactory(layout.sstable, files, faults, BloomFilterFactory(), 4096, 0.01)
        state = LiveState(ManifestStore(layout.manifest, files, faults), self.versions,
                          ManifestState(0, 1, 0, 1, 1), active_segment=1)
        flusher = Flusher(self.versions, FakeWal(), state, tables, new_memtable, files, faults, SwapLock(), MINUTE)
        policy = TimeWindowPolicy((MINUTE, 2 * MINUTE, 4 * MINUTE), 2, 0.10, 4 * MINUTE)
        self.worker = BackgroundWorker(self.versions, flusher, Compactor(self.versions, state, tables, faults),
                                       policy, max_immutable_memtables=1, smallest_window_ms=MINUTE)

    def write(self, *points):
        self.versions.current().active.apply(list(points))
        self.worker.wake()

    def files(self):
        return [t.name for _, ts in self.versions.current().windows for t in ts]


@pytest.fixture
def engine(tmp_path):
    e = Engine(tmp_path, max_entries=3)
    e.worker.start()
    yield e
    e.worker.stop()


def test_b1_a_full_memtable_is_flushed_by_the_flush_thread(engine):
    engine.write(Point(1, T, 1, 30.1), Point(2, T, 2, 28.0), Point(3, T, 3, 32.5))   # 3 = max_entries

    assert eventually(lambda: engine.files() == ["000001.sst"] and not engine.versions.current().immutables)


def test_b1_run_until_idle_flushes_everything_then_compacts_until_nothing_is_left(tmp_path):
    e = Engine(tmp_path)
    for seq in (1, 2):                                   # two flushes into the same minute -> 2 files
        e.versions.current().active.apply([Point(1, T + seq, seq, float(seq))])
        e.worker.run_until_idle()

    assert e.files() == ["000003.sst"]                   # 2 files in one window (threshold 2) -> merged
    assert list(e.versions.current().windows[0][1][0].iter_all()) == [Point(1, T + 1, 1, 1.0),
                                                                     Point(1, T + 2, 2, 2.0)]
