"""Run device smoke tests for all libraries through the lightweight harness.

Discovers and exercises device_tests/ for every library under libraries/,
not just a single hardcoded package.  Avoids ``os.path`` (unavailable on
some CircuitPython builds) and keeps the import footprint minimal so it can
execute under CPython, MicroPython unix-port, and CircuitPython unix-port.

See ``plans/decisions/0006-shared-import-free-compatibility-smoke-runner.md``.
"""

import os
import sys


def _is_dir(path):
    """Return True if *path* is an existing directory."""
    try:
        os.listdir(path)
        return True
    except OSError:
        return False


def _sorted_listdir(path):
    """Return a sorted listing of *path*, or an empty list on failure."""
    try:
        entries = os.listdir(path)
        entries.sort()
        return entries
    except OSError:
        return []


def _discover_source_roots():
    """Return src/ directories under libraries/ and support/."""
    roots = []
    for parent in ("libraries", "support"):
        for name in _sorted_listdir(parent):
            src = parent + "/" + name + "/src"
            if _is_dir(src):
                roots.append(src)
    return roots


def _discover_device_tests():
    """Return paths to all test_*.py files under libraries/*/device_tests/."""
    tests = []
    for name in _sorted_listdir("libraries"):
        dt_dir = "libraries/" + name + "/device_tests"
        for filename in _sorted_listdir(dt_dir):
            if filename.startswith("test_") and filename.endswith(".py"):
                tests.append(dt_dir + "/" + filename)
    return tests


def _setup_source_paths():
    """Insert discovered source roots into sys.path so library imports resolve."""
    for root in _discover_source_roots():
        if root not in sys.path:
            sys.path.insert(0, root)


class _Namespace:
    """Attribute container for exec'd module globals."""


def _exec_as_namespace(path, name="__main__", package=""):
    """Execute a .py file and return a namespace object with its globals."""
    ns = {"__name__": name, "__file__": path, "__package__": package}
    with open(path) as fh:
        exec(fh.read(), ns)
    obj = _Namespace()
    for key in ns:
        setattr(obj, key, ns[key])
    return obj


def main():
    """Discover and run all device tests, returning a shell exit code."""
    _setup_source_paths()

    test_files = _discover_device_tests()
    if not test_files:
        print("NO DEVICE TESTS FOUND")
        return 0

    runner = _exec_as_namespace(
        "support/test_harness/src/chumicro_test_harness/runner.py",
        "chumicro_test_harness.runner",
        "chumicro_test_harness",
    )

    total_failed = 0
    for path in test_files:
        print(f"== {path} ==")
        try:
            test_mod = _exec_as_namespace(path)
        except Exception as exc:
            total_failed += 1
            print(f"ERROR loading {path}: {exc}")
            continue
        result = runner.run_module(test_mod)
        if result != 0:
            total_failed += 1

    return 1 if total_failed else 0


raise SystemExit(main())
