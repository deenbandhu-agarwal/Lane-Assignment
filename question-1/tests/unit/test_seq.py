"""SequenceCounter with visible seq (seam E1, design-qa #45 D1)."""

import threading

from tsdb.engine.seq import SequenceCounter


def test_blocks_are_consecutive_and_start_after_the_recovered_seq():
    seq = SequenceCounter(last=10)

    assert seq.next_block(3) == 11          # 11, 12, 13
    assert seq.next_block(2) == 14          # 14, 15
    assert seq.last == 15


def test_visible_waits_for_every_older_block_even_if_a_newer_one_applies_first():
    seq = SequenceCounter()
    wal_a = seq.next_block(3)               # seq 1-3, still fsyncing
    wal_b = seq.next_block(2)               # seq 4-5

    seq.mark_applied(wal_b, 2)              # B finishes first
    assert seq.visible == 0                 # 1-3 not applied: showing 4-5 would be a torn read

    seq.mark_applied(wal_a, 3)
    assert seq.visible == 5


def test_a_reply_waits_until_its_seq_is_visible():
    seq = SequenceCounter()
    wal_a, wal_b = seq.next_block(1), seq.next_block(1)
    seq.mark_applied(wal_b, 1)
    replied = threading.Event()

    def writer_b_replies():
        seq.wait_until_visible(2)
        replied.set()

    t = threading.Thread(target=writer_b_replies)
    t.start()
    assert not replied.wait(0.05)           # seq 1 is not applied yet: B must not reply
    seq.mark_applied(wal_a, 1)
    assert replied.wait(1.0)
    t.join()


def test_observe_moves_the_counter_forward_never_back():
    seq = SequenceCounter(last=50)

    seq.observe(100)
    seq.observe(70)

    assert seq.next_block(1) == 101
