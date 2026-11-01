"""The only test that runs during scaffolding: every module imports cleanly (no cycles)."""

import importlib
import pkgutil

import tsdb


def test_every_module_imports():
    names = [m.name for m in pkgutil.walk_packages(tsdb.__path__, "tsdb.")]
    assert names, "no modules found"
    for name in names:
        importlib.import_module(name)


def test_running_free_threaded():
    import sys
    import sysconfig

    assert sysconfig.get_config_var("Py_GIL_DISABLED"), "expected the free-threaded (3.14t) build"
    assert not sys._is_gil_enabled(), "GIL got re-enabled (an extension without free-threading support?)"
