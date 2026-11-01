"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_insert_keeps_sorted_order():
    """Random inserts -> iteration is sorted by (series, ts, seq desc)."""


def test_all_versions_kept_newest_first():
    """Same (series, ts) twice -> both kept, higher seq first."""


def test_iter_from_seeks_correctly():
    """iter_from(key) starts at the first entry >= key."""


def test_height_distribution():
    """Seeded: ~75% height 1, ~19% height 2 ...; never above max_level."""


def test_reader_never_sees_broken_list_during_inserts():
    """Reader thread walks while writer inserts (free-threaded)."""
