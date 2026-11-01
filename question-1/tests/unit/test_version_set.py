"""VersionSet: snapshots and safe file deletion (seam E3)."""

from tsdb.engine.version import Version, VersionSet
from tsdb.model import TimeWindow

HOUR = 3_600_000
W_10 = TimeWindow(HOUR, 1_730_368_800_000)


class FakeTable:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


A, B, C, MERGED = FakeTable("000001.sst"), FakeTable("000002.sst"), FakeTable("000003.sst"), FakeTable("000004.sst")


def version(number, *tables):
    return Version(number=number, active=None, immutables=(), windows=((W_10, tables),), newest_data_ts=0)


def make(initial):
    deleted = []
    return VersionSet(initial, on_obsolete=deleted.append), deleted


def test_a_snapshot_holds_the_current_version_and_the_seq_it_was_taken_at():
    versions, _ = make(version(1, A, B))

    snap = versions.acquire(seq=42)

    assert (snap.version.number, snap.seq) == (1, 42)
    assert versions.current().number == 1


def test_a_running_query_keeps_seeing_old_files_after_compaction_and_they_are_deleted_after_it_ends():
    versions, deleted = make(version(1, A, B))
    query = versions.acquire(seq=42)

    versions.install(version(2, MERGED))                      # compaction: A + B -> MERGED

    assert query.version.windows[0][1] == (A, B)              # the query still reads A and B
    assert versions.current().number == 2
    assert deleted == []                                      # not while the query runs

    versions.release(query)
    assert sorted(t.name for t in deleted) == ["000001.sst", "000002.sst"]


def test_with_no_query_running_replaced_files_are_deleted_at_install():
    versions, deleted = make(version(1, A, B))

    versions.install(version(2, MERGED))

    assert sorted(t.name for t in deleted) == ["000001.sst", "000002.sst"]


def test_a_file_kept_by_the_new_version_is_never_deleted():
    versions, deleted = make(version(1, A, B))

    versions.install(version(2, A, B, C))                     # flush: C added, A and B stay

    assert deleted == []


def test_a_file_is_deleted_only_when_the_last_of_several_snapshots_using_it_ends():
    versions, deleted = make(version(1, A, B))
    q1 = versions.acquire(seq=10)
    versions.install(version(2, A, C))                        # B replaced by C
    q2 = versions.acquire(seq=11)
    q1_again = versions.acquire(seq=12)                       # (another query on version 2)
    versions.install(version(3, MERGED))                      # A + C -> MERGED

    versions.release(q2)
    assert deleted == []                                      # q1 still uses version 1 (A, B)
    versions.release(q1_again)
    assert [t.name for t in deleted] == ["000003.sst"]        # C only lived in version 2
    versions.release(q1)
    assert sorted(t.name for t in deleted) == ["000001.sst", "000002.sst", "000003.sst"]
    assert deleted.count(A) == 1                              # never deleted twice
