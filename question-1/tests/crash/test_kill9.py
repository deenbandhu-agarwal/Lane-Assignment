"""Scaffold: each test states the property it must prove."""

import pytest

pytestmark = [pytest.mark.crash, pytest.mark.skip(reason="scaffold: not implemented")]


def test_kill9_during_writes_loses_no_acked_write():
    """Child server, many writers, SIGKILL at random time -> every acked point readable after restart."""
