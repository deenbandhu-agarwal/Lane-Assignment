"""WAL writer group commit with real files (seams W1-W2)."""

import threading
import time

import pytest

from tsdb.engine.seq import SequenceCounter
from tsdb.errors import FatalStorageError
from tsdb.faults import NoFaults
from tsdb.model import Point
from tsdb.storage.fileio import OsFileOps
from tsdb.wal.record import scan
from tsdb.wal.segment import WalSegment
from tsdb.wal.writer import PendingPut, Ticket, WalWriter

T_10_00 = 1_730_368_800_000


class SlowFsyncFiles(OsFileOps):
    """Real files; every fsync takes 2 ms (like a real disk) and is logged with the other events."""

    def __init__(self, events):
        self.events = events

    def fsync(self, fd):
        time.sleep(0.002)
        super().fsync(fd)
        self.events.append("wal fsync")


def make_writer(tmp_path, events, applied, files=None):
    files = files or SlowFsyncFiles(events)
    segment = WalSegment(tmp_path / "000001.log", files)
    segment.open()
    events.clear()                                            # ignore the directory fsync at create
    writer = WalWriter(segment, SequenceCounter(), threading.Lock(),
                       apply=applied.extend, before_fsync=lambda: events.append("series.log fsync"),
                       faults=NoFaults())
    writer.start()
    return writer


def test_many_writers_share_fsyncs_and_every_reply_comes_after_fsync_and_apply(tmp_path):
    events, applied = [], []
    writer = make_writer(tmp_path, events, applied)
    late_replies = []

    def client(c):
        for i in range(25):
            value = c * 1000 + i
            ticket = Ticket([PendingPut(series_id=c + 1, timestamp=T_10_00 + i, value=float(value))])
            writer.submit(ticket)
            ticket.done.wait()
            if float(value) not in {p.value for p in list(applied)}:
                late_replies.append(value)                    # replied before it was in the memtable

    clients = [threading.Thread(target=client, args=(c,)) for c in range(8)]
    for t in clients:
        t.start()
    for t in clients:
        t.join()
    writer.stop()

    fsyncs = events.count("wal fsync")
    assert late_replies == []
    assert len(applied) == 200
    assert 1 <= fsyncs < 200                                  # group commit: fewer fsyncs than writes
    assert [p.seq for p in applied] == list(range(1, 201))    # seq order = apply order (1 WAL)
    on_disk = scan((tmp_path / "000001.log").read_bytes())
    assert [r.entry.seq for r in on_disk.records] == list(range(1, 201))   # and = file order
    assert all(events[i - 1] == "series.log fsync" for i, e in enumerate(events) if e == "wal fsync")
    print(f"\n200 writes from 8 threads -> {fsyncs} WAL fsyncs")


class FailingFsyncFiles(SlowFsyncFiles):
    """The disk dies: every WAL fsync fails (FileOps turns that into FatalStorageError)."""

    def fsync(self, fd):
        raise FatalStorageError("fsync failed: EIO")

    def fsync_dir(self, path):
        pass                                                  # creating the segment still works


def test_a_failed_fsync_fails_every_waiting_write_and_nothing_reaches_the_memtable(tmp_path):
    events, applied = [], []
    writer = make_writer(tmp_path, events, applied, files=FailingFsyncFiles(events))
    tickets = [Ticket([PendingPut(1, T_10_00 + i, float(i))]) for i in range(5)]

    for t in tickets:
        writer.submit(t)
    for t in tickets:
        assert t.done.wait(1)

    assert all(isinstance(t.error, FatalStorageError) for t in tickets)
    assert applied == []


def test_after_a_failed_fsync_the_writer_refuses_new_writes_instead_of_retrying(tmp_path):
    events, applied = [], []
    writer = make_writer(tmp_path, events, applied, files=FailingFsyncFiles(events))
    first = Ticket([PendingPut(1, T_10_00, 1.0)])
    writer.submit(first)
    first.done.wait(1)

    later = Ticket([PendingPut(1, T_10_00 + 1, 2.0)])
    writer.submit(later)

    assert later.done.wait(1)
    assert isinstance(later.error, FatalStorageError)          # a retried fsync could "succeed" on lost pages
    assert applied == []
