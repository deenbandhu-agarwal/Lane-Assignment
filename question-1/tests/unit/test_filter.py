"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_parse_precedence_and_parens():
    """(a=1 OR a=2) AND b!=3 parses to the right tree."""


def test_syntax_error_reports_position():
    """Bad input -> FilterSyntaxError with position."""


def test_not_equal_is_set_difference():
    """k!=v = universe - posting(k=v); series without k match."""


def test_and_starts_from_smallest_list():
    """Evaluation order uses posting sizes (no full scans)."""
