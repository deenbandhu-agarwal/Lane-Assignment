"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = pytest.mark.skip(reason="scaffold: not implemented")


def test_commit_is_atomic():
    """Crash between MANIFEST.tmp write and rename -> old state loads."""


def test_checksum_detects_damage():
    """Damaged MANIFEST -> CorruptFileError."""
