"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_window_alignment_from_epoch():
    """TimeWindow.containing(ts, size).start = ts - ts % size; end = start + size - 1."""


def test_windows_nest_exactly():
    """Every 1 h window has exactly one 6 h parent and one 1 day parent; children() round-trips."""


def test_closed_uses_data_time_with_grace():
    """Closed iff newest_data_ts > end + one smallest window; wall clock never consulted."""


def test_tombstone_clip_per_window():
    """A delete 10:30-12:15 clips into 10:30-10:59:59.999, 11:00-11:59:59.999, 12:00-12:15."""


def test_flush_split_by_window():
    """split_by_window: points and clipped tombstones grouped per smallest window, order kept."""
