"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_repeated_compaction_no_loss_no_duplicates():
    """Seeded writes/overwrites/deletes + dict oracle; after each of N compaction rounds every query matches."""


def test_every_table_stays_inside_one_window():
    """After flushes (incl. edge-crossing memtables and late points) and compactions, each table's
    min/max timestamp lies inside its window."""


def test_size_tiered_inside_window_only():
    """A window with >= threshold tables is merged; tables of different windows are never mixed."""


def test_move_up_when_all_children_closed():
    """When every 1 h child of a 6 h window is closed (data time), they become one 6 h table."""


def test_tombstone_dropped_only_by_rule_2():
    """Partial job inside a window keeps the tombstone (no zombie data); a job over the whole window drops it."""


def test_late_files_merge_threshold():
    """Small late tables inside a moved-up window wait until >= 10% of its size (or the daily pass)."""
