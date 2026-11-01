"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_repeated_compaction_no_loss_no_duplicates():
    """Seeded data, N compactions -> exact same multiset of points."""


def test_tombstones_dropped_only_at_bottom():
    """Tombstone kept while older data may exist below; no zombie data."""
