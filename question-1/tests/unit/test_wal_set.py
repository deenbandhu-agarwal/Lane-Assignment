"""WalSet over 2 real WALs + replay (seam W3). A fake router fixes which WAL each series uses."""

import pytest

from tsdb.engine.seq import SequenceCounter
from tsdb.engine.swap_lock import SwapLock
from tsdb.faults import NoFaults
from tsdb.model import Point, SeriesKey, Tombstone
from tsdb.storage.fileio import OsFileOps
from tsdb.wal.record import scan
from tsdb.wal.wal_set import WalReplayer, WalSet, new_segment
from tsdb.wal.writer import WalWriter

T_10_00 = 1_730_368_800_000
DELHI, MUMBAI, CHENNAI = (SeriesKey.of("temperature", {"city": c}) for c in ("Delhi", "Mumbai", "Chennai"))
ROUTE = {DELHI: 0, CHENNAI: 0, MUMBAI: 1}


class FakeRouter:
    def route(self, key):
        return ROUTE[key]


class FakeMemtable:
    def __init__(self):
        self.entries = []

    def apply(self, entries):
        self.entries.extend(entries)


def path_of(tmp_path):
    return lambda wal, seg: tmp_path / f"wal{wal}" / f"{seg:06d}.log"


@pytest.fixture
def wals(tmp_path):
    files, seq, memtable = OsFileOps(), SequenceCounter(), FakeMemtable()
    for i in range(2):
        (tmp_path / f"wal{i}").mkdir()
    writers = [WalWriter(i, new_segment(path_of(tmp_path)(i, 1), files), seq, SwapLock(), memtable.apply,
                         before_fsync=lambda: None, faults=NoFaults()) for i in range(2)]
    for w in writers:
        w.start()
    wal_set = WalSet(writers, FakeRouter(), path_of(tmp_path), files)
    yield wal_set, memtable, tmp_path
    wal_set.close()


def records(path):
    return [r.entry for r in scan(path.read_bytes()).records]


def test_each_series_goes_to_its_own_wal_and_everything_reaches_the_memtable(wals):
    wal_set, memtable, tmp_path = wals

    wal_set.write([(DELHI, 1, T_10_00, 30.1), (MUMBAI, 3, T_10_00, 32.5), (CHENNAI, 4, T_10_00, 35.0)])

    assert {(p.series_id, p.value) for p in records(tmp_path / "wal0" / "000001.log")} == {(1, 30.1), (4, 35.0)}
    assert {(p.series_id, p.value) for p in records(tmp_path / "wal1" / "000001.log")} == {(3, 32.5)}
    assert sorted(p.value for p in memtable.entries) == [30.1, 32.5, 35.0]


def test_a_delete_copy_goes_to_every_wal_holding_its_series_and_names_only_that_wals_series(wals):
    wal_set, memtable, tmp_path = wals

    wal_set.delete([(DELHI, 1), (MUMBAI, 3), (CHENNAI, 4)], T_10_00, T_10_00 + 60_000)

    [in_wal0] = records(tmp_path / "wal0" / "000001.log")
    [in_wal1] = records(tmp_path / "wal1" / "000001.log")
    assert (in_wal0.series_ids, in_wal0.from_ts, in_wal0.to_ts) == ((1, 4), T_10_00, T_10_00 + 60_000)
    assert in_wal1.series_ids == (3,)
    assert len(memtable.entries) == 2


def test_rotate_all_starts_new_segments_and_sends_later_writes_to_the_new_memtable(wals):
    wal_set, old_memtable, tmp_path = wals
    wal_set.write([(DELHI, 1, T_10_00, 30.1)])
    new_memtable = FakeMemtable()

    old_paths = wal_set.rotate_all(2, new_memtable)
    wal_set.write([(DELHI, 1, T_10_00 + 1, 30.2), (MUMBAI, 3, T_10_00 + 1, 32.6)])

    assert sorted(old_paths) == [tmp_path / "wal0" / "000001.log", tmp_path / "wal1" / "000001.log"]
    assert [p.value for p in old_memtable.entries] == [30.1]
    assert sorted(p.value for p in new_memtable.entries) == [30.2, 32.6]
    assert [p.value for p in records(tmp_path / "wal0" / "000002.log")] == [30.2]


def test_replay_reads_every_live_segment_of_every_wal_and_repairs_a_cut_tail(wals):
    wal_set, _, tmp_path = wals
    wal_set.write([(DELHI, 1, T_10_00, 30.1), (MUMBAI, 3, T_10_00, 32.5)])
    wal_set.rotate_all(2, FakeMemtable())
    wal_set.write([(DELHI, 1, T_10_00 + 1, 30.2), (MUMBAI, 3, T_10_00 + 1, 32.6)])
    wal_set.close()
    cut = tmp_path / "wal1" / "000002.log"
    cut.write_bytes(cut.read_bytes()[:-3])                    # crash cut Mumbai's last record

    replayed = [r.entry for r in WalReplayer(OsFileOps(), path_of(tmp_path)).replay(wal_count=2, from_segment=1)]

    assert sorted(p.value for p in replayed) == [30.1, 30.2, 32.5]
    assert cut.stat().st_size == 0                            # truncated to the last good record
