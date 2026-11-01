"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_flush_split_by_window():
    """split_by_window: points and clipped tombstones grouped per smallest window, order kept."""
