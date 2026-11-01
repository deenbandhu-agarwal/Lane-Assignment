"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = [pytest.mark.crash, pytest.mark.skip(reason="scaffold: not implemented")]


def test_crash_at_wal_append():
    """TSDB_CRASH_AT=wal_append -> restart: acked writes present, files valid."""


def test_crash_at_memtable_flush():
    """TSDB_CRASH_AT=memtable_flush"""


def test_crash_at_sstable_write():
    """TSDB_CRASH_AT=sstable_write"""


def test_crash_at_manifest_update():
    """TSDB_CRASH_AT=manifest_update"""


def test_crash_at_compaction_swap():
    """TSDB_CRASH_AT=compaction_swap"""
