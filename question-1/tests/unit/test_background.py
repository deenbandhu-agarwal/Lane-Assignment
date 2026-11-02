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
    def __init__(self, tmp):
        self.memtable, self.tmp = None, tmp

    def rotate(self, new_segment_no, new_memtable):
        self.memtable = new_memtable
        return self.tmp / f"{new_segment_no - 1:06d}.log"      # never written: removing it is a no-op


class Engine:
    """Real flush + compaction pieces; steps 1 -> 2 -> 4 minutes, merge at 2 (as in the example)."""

    def __init__(self, tmp_path, max_entries=10**9):
        files, faults = OsFileOps(), NoFaults()
        layout = ShardLayout(tmp_path)
        new_memtable = lambda: Memtable(SkipList(random.Random(1)), 10**9, 100, max_entries)
        self.versions = VersionSet(Version(0, new_memtable(), (), (), 0), on_obsolete=lambda t: None)
        tables = SSTableFactory(layout.sstable, files, faults, BloomFilterFactory(), 4096, 0.01)
        state = LiveState(ManifestStore(layout.manifest, files, faults), self.versions,
                          ManifestState(0, 1, 0, 1), active_segment=1)
        flusher = Flusher(self.versions, FakeWal(tmp_path), state, tables, new_memtable, files, faults, threading.Lock(), MINUTE)
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


@pytest.fixture
def roomy(tmp_path):
    e = Engine(tmp_path)                                   # never full
    e.worker.start()
    yield e
    e.worker.stop()


def test_b2_a_memtable_whose_oldest_window_is_closed_is_flushed_even_if_not_full(roomy):
    # oldest window 10:00 ends 10:00:59.999; grace 1 min -> closed once newest data > 10:01:59.999
    roomy.write(Point(1, T, 1, 30.1), Point(1, T + 2 * MINUTE, 2, 31.0))

    assert eventually(lambda: roomy.files() != [])


def test_b2_no_flush_while_the_oldest_window_can_still_get_writes(roomy):
    roomy.write(Point(1, T, 1, 30.1), Point(1, T + 2 * MINUTE - 1, 2, 31.0))   # exactly end + grace

    assert not eventually(lambda: roomy.files() != [], timeout=0.3)


def test_b2_a_memtable_of_only_late_points_is_flushed_when_flushed_data_is_already_newer(roomy):
    roomy.write(Point(1, T + 10 * MINUTE, 1, 1.0), Point(1, T + 13 * MINUTE, 2, 2.0))   # closes 10:10
    assert eventually(lambda: roomy.files() != [])
    before = roomy.files()

    roomy.write(Point(2, T, 3, 9.9))                       # late point for 10:00; memtable's own newest = 10:00

    assert eventually(lambda: len(roomy.files()) > len(before))


class FakeMem:
    def __init__(self, full=False):
        self.full, self.max_seq, self.max_timestamp, self.min_timestamp = full, 1, 0, None

    def is_full(self):
        return self.full


class FakeFlusher:
    """swap: frozen -> immutables. flush: waits for `gate`, then the frozen memtable leaves."""

    def __init__(self, versions):
        self.versions, self.gate, self.flushed = versions, threading.Event(), 0

    def swap_memtable(self):
        v = self.versions.current()
        self.versions.install(Version(v.number + 1, FakeMem(), (v.active, *v.immutables), v.windows, 0))
        return v.active

    def flush(self, frozen):
        self.gate.wait()
        v = self.versions.current()
        self.versions.install(Version(v.number + 1, v.active, tuple(m for m in v.immutables if m is not frozen),
                                      v.windows, 0))
        self.flushed += 1


class SlowCompactor:
    def __init__(self):
        self.gate, self.started = threading.Event(), threading.Event()

    def run(self, job):
        self.started.set()
        self.gate.wait()


class OneJobPolicy:
    def __init__(self):
        self.given = False

    def pick(self, version):
        if self.given:
            return None
        self.given = True
        return "job"


def fake_worker(compactor=None, policy=None):
    versions = VersionSet(Version(0, FakeMem(full=True), (), (), 0), on_obsolete=lambda t: None)
    flusher = FakeFlusher(versions)
    worker = BackgroundWorker(versions, flusher, compactor or SlowCompactor(), policy or (lambda: None),
                              max_immutable_memtables=1, smallest_window_ms=MINUTE)
    if policy is None:
        worker._policy = type("NoJobs", (), {"pick": lambda self, v: None})()
    return versions, flusher, worker


def test_b3_writers_wait_while_the_active_memtable_is_full_and_one_is_already_waiting_for_flush():
    versions, flusher, worker = fake_worker()
    worker.start()
    worker.wake()
    assert eventually(lambda: len(versions.current().immutables) == 1)   # flush started, stuck on the gate
    versions.current().active.full = True                                 # the new one fills up too
    room = threading.Event()
    writer = threading.Thread(target=lambda: (worker.wait_for_room(), room.set()))
    writer.start()

    assert not room.wait(0.2)                                             # memory is bounded: writer waits
    flusher.gate.set()                                                    # the flush finishes
    assert room.wait(2)
    writer.join()
    worker.stop()


def test_b3_a_writer_does_not_wait_when_there_is_room():
    versions, flusher, worker = fake_worker()
    versions.current().active.full = False

    worker.wait_for_room()                                                # returns at once


def test_b4_a_long_compaction_does_not_stop_a_flush():
    compactor = SlowCompactor()
    versions, flusher, worker = fake_worker(compactor, OneJobPolicy())
    flusher.gate.set()
    worker.start()
    worker._compact_wake.set()
    assert compactor.started.wait(1)                                      # compaction is running (blocked)

    worker.wake()                                                         # active memtable is full

    assert eventually(lambda: flusher.flushed == 1)                      # flushed while compaction runs
    compactor.gate.set()
    worker.stop()
