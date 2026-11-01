"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_write_then_read_roundtrip():
    """Points + tombstones survive write/open/read."""


def test_footer_read_first_and_validated():
    """Bad magic / checksum -> CorruptFileError."""


def test_sparse_index_finds_block():
    """Seek (series, from) reads only the needed blocks."""


def test_forward_cursor_reuses_block():
    """Neighbour series in one block -> block read once."""


def test_may_contain_uses_footer_and_bloom():
    """Out-of-range series/time and Bloom 'no' -> skipped."""
