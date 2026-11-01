"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_put_and_delete_roundtrip():
    """encode -> scan gives back the same entries."""


def test_scan_stops_at_cut_record():
    """File cut mid-record -> valid prefix only, reason 'cut record'."""


def test_scan_stops_at_bad_checksum():
    """One flipped byte -> stop at that record."""
