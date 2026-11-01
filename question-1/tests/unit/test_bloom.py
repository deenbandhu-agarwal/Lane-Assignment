"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_optimal_params_for_1_percent():
    """n=10_000, p=0.01 -> m ~ 95_851 bits, k = 7 (show the math in README)."""


def test_no_false_negatives():
    """Every added id -> may_contain is True."""


def test_measured_false_positive_rate():
    """1M absent ids -> measured FPR close to 1%; value reported in README."""


def test_roundtrip_bytes():
    """to_bytes/from_bytes keeps answers identical."""
