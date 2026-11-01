"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = [pytest.mark.stress, pytest.mark.skip(reason="scaffold: not implemented")]


def test_no_torn_reads_during_writes_and_compaction():
    """Readers check invariants of a consistent snapshot while writers + compaction run."""
