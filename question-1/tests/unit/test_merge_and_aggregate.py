"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_newest_seq_wins():
    """Same timestamp in memtable and SSTable -> higher seq returned once."""


def test_tombstone_hides_only_older_seq():
    """Write after delete (higher seq) stays visible."""


def test_bucket_alignment_from_epoch():
    """bucket_start = ts - ts % size; first bucket may start before `from`."""


def test_each_aggregation():
    """avg/sum/min/max/count over known data."""
