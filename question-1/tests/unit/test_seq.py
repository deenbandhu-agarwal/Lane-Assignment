"""SequenceCounter: last handed out vs visible (applied)."""

from tsdb.engine.seq import SequenceCounter


def test_blocks_are_consecutive_and_start_after_the_recovered_seq():
    seq = SequenceCounter(last=10)

    assert seq.next_block(3) == 11          # 11, 12, 13
    assert seq.next_block(2) == 14          # 14, 15
    assert seq.last == 15


def test_a_block_becomes_visible_only_once_it_is_applied():
    seq = SequenceCounter(last=10)
    first = seq.next_block(3)               # 11-13 handed out, still fsyncing

    assert (seq.last, seq.visible) == (13, 10)   # a query now must not see 11-13
    seq.mark_applied(first, 3)
    assert seq.visible == 13


def test_observe_moves_the_counter_forward_never_back():
    seq = SequenceCounter(last=50)

    seq.observe(100)
    seq.observe(70)

    assert seq.next_block(1) == 101
