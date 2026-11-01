"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_duplicate_timestamp_last_write_wins():
    """Same series+ts twice -> latest value, once, across memtable/SSTable/compaction."""


def test_delete_survives_flush_compaction_restart():
    """Tombstone hides data in SSTables; still hidden after compaction and restart."""


def test_write_after_delete_is_visible():
    """New point in a deleted range (higher seq) is returned."""
