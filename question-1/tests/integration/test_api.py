"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_write_query_roundtrip():
    """POST /write then GET /query returns the points (raw + agg)."""


def test_series_endpoint_uses_index_only():
    """GET /series lists matching series; no data blocks read."""


def test_error_codes():
    """Bad body / filter / range -> 400 with JSON error."""
