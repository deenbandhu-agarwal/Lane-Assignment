"""Wal over one real writer + replay (seam W3)."""

import threading
import pytest

from tsdb.engine.seq import SequenceCounter
from tsdb.faults import NoFaults
from tsdb.model import Tombstone
from tsdb.storage.fileio import OsFileOps
from tsdb.wal.record import scan
from tsdb.wal.wal import Wal, WalReplayer, new_segment
from tsdb.wal.writer import WalWriter

T_10_00 = 1_730_368_800_000
DELHI, MUMBAI = 1, 3


class FakeMemtable:
    def __init__(self):
        self.entries = []

    def apply(self, entries):
        self.entries.extend(entries)


def path_of(tmp_path):
    return lambda seg: tmp_path / f"{seg:06d}.log"


@pytest.fixture
def wal(tmp_path):
    files, memtable = OsFileOps(), FakeMemtable()
    writer = WalWriter(new_segment(path_of(tmp_path)(1), files), SequenceCounter(), threading.Lock(), memtable.apply,
                       before_fsync=lambda: None, faults=NoFaults())
    writer.start()
    w = Wal(writer, path_of(tmp_path), files)
    yield w, memtable, tmp_path
    w.close()


def records(path):
    return [r.entry for r in scan(path.read_bytes()).records]


def test_a_write_is_on_disk_and_in_the_memtable_with_rising_seqs(wal):
    w, memtable, tmp_path = wal

    w.write([(DELHI, T_10_00, 30.1), (MUMBAI, T_10_00, 32.5)])

    assert [(p.seq, p.series_id, p.value) for p in records(tmp_path / "000001.log")] == [
        (1, DELHI, 30.1), (2, MUMBAI, 32.5)]
    assert [p.value for p in memtable.entries] == [30.1, 32.5]


def test_a_delete_is_one_record_naming_every_series(wal):
    w, memtable, tmp_path = wal

    w.delete([MUMBAI, DELHI], T_10_00, T_10_00 + 60_000)

    assert records(tmp_path / "000001.log") == [Tombstone(1, (DELHI, MUMBAI), T_10_00, T_10_00 + 60_000)]
    assert len(memtable.entries) == 1


def test_rotate_starts_a_new_segment_and_sends_later_writes_to_the_new_memtable(wal):
    w, old_memtable, tmp_path = wal
    w.write([(DELHI, T_10_00, 30.1)])
    new_memtable = FakeMemtable()

    old_path = w.rotate(2, new_memtable)
    w.write([(DELHI, T_10_00 + 1, 30.2)])

    assert old_path == tmp_path / "000001.log"
    assert [p.value for p in old_memtable.entries] == [30.1]
    assert [p.value for p in new_memtable.entries] == [30.2]
    assert [p.value for p in records(tmp_path / "000002.log")] == [30.2]


def test_replay_reads_every_live_segment_in_order_and_repairs_a_cut_tail(wal):
    w, _, tmp_path = wal
    w.write([(DELHI, T_10_00, 30.1)])
    w.rotate(2, FakeMemtable())
    w.write([(DELHI, T_10_00 + 1, 30.2), (MUMBAI, T_10_00 + 1, 32.6)])
    w.close()
    cut = tmp_path / "000002.log"
    cut.write_bytes(cut.read_bytes()[:-3])                    # crash cut the last record

    replayed = [r.entry for r in WalReplayer(OsFileOps(), path_of(tmp_path)).replay(from_segment=1)]

    assert [p.value for p in replayed] == [30.1, 30.2]
    assert len(records(cut)) == 1 and cut.stat().st_size == len(cut.read_bytes())
