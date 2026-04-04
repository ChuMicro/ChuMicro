"""Run cross-runtime unit tests for all libraries through the lightweight harness.

Discovers and exercises tests/ for every library under libraries/,
skipping files that fail to import (e.g. because they require pytest).
Avoids ``os.path`` (unavailable on some CircuitPython builds) and keeps
the import footprint minimal so it can execute under CPython, MicroPython
unix-port, and CircuitPython unix-port.

See ``plans/decisions/0016-cross-runtime-unit-tests.md``.
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


def _discover_tests():
    """Return paths to all test_*.py files under libraries/*/tests/."""
    tests = []
    for name in _sorted_listdir("libraries"):
        t_dir = "libraries/" + name + "/tests"
        for filename in _sorted_listdir(t_dir):
            if filename.startswith("test_") and filename.endswith(".py"):
                tests.append(t_dir + "/" + filename)
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
    """Discover and run all cross-runtime unit tests, returning a shell exit code."""
    _setup_source_paths()

    test_files = _discover_tests()
    if not test_files:
        print("NO TESTS FOUND")
        return 0

    runner = _exec_as_namespace(
        "support/test_harness/src/chumicro_test_harness/runner.py",
        "chumicro_test_harness.runner",
        "chumicro_test_harness",
    )

    total_failed = 0
    skipped = 0
    for path in test_files:
        print(f"== {path} ==")
        try:
            test_mod = _exec_as_namespace(path)
        except ImportError as exc:
            skipped += 1
            print(f"SKIP {path} (import failed: {exc})")
            continue
        except Exception as exc:
            total_failed += 1
            print(f"ERROR loading {path}: {exc}")
            continue
        result = runner.run_module(test_mod)
        if result != 0:
            total_failed += 1

    if skipped:
        print(f"Skipped {skipped} file(s) (import errors, likely pytest-only)")

    return 1 if total_failed else 0


raise SystemExit(main())
