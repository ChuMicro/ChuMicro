"""Cross-runtime test discovery and orchestration.

Discovers ``tests/`` for every library under ``libraries/``, sets up
``sys.path`` so library imports resolve, and runs each test file through
the lightweight harness runner.

Avoids ``os.path`` (unavailable on some CircuitPython builds) and keeps
the import footprint minimal so it can execute under CPython, MicroPython
unix-port, and CircuitPython unix-port.

See ``plans/decisions/0016-cross-runtime-unit-tests.md``.
"""

import os
import sys

from .runner import run_module


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


def discover_source_roots(root="."):
    """Return ``src/`` directories under ``libraries/`` and ``support/``.

    *root* is the workspace root directory, defaulting to the current
    working directory.
    """
    roots = []
    for parent in ("libraries", "support"):
        parent_path = root + "/" + parent if root != "." else parent
        for name in _sorted_listdir(parent_path):
            src = parent_path + "/" + name + "/src"
            if _is_dir(src):
                roots.append(src)
    return roots


def discover_tests(root=".", libraries=None):
    """Return paths to all ``test_*.py`` files under ``libraries/*/tests/``.

    *root* is the workspace root directory, defaulting to the current
    working directory.

    *libraries* is an optional list of library names to include.  When
    ``None``, all libraries are discovered.  Used by platform targeting
    to skip libraries that don't target the current runtime.
    """
    libs_path = root + "/libraries" if root != "." else "libraries"
    lib_filter = set(libraries) if libraries else None
    tests = []
    for name in _sorted_listdir(libs_path):
        if lib_filter is not None and name not in lib_filter:
            continue
        tests_dir = libs_path + "/" + name + "/tests"
        for filename in _sorted_listdir(tests_dir):
            if filename.startswith("test_") and filename.endswith(".py"):
                if filename.endswith("_pytest.py"):
                    continue
                tests.append(tests_dir + "/" + filename)
    return tests


def setup_source_paths(root="."):
    """Insert discovered source roots into ``sys.path`` so library imports resolve."""
    for src_root in discover_source_roots(root):
        if src_root not in sys.path:
            sys.path.insert(0, src_root)


class _Namespace:
    """Attribute container for exec'd module globals."""


def _exec_as_namespace(path, name="__main__", package=""):
    """Execute a ``.py`` file and return a namespace object with its globals.

    Uses ``exec()`` rather than the standard import machinery because
    multiple libraries have test files with identical names (e.g.
    ``test_core.py``), and MicroPython/CircuitPython lack
    ``importlib.util`` for file-path-based imports.
    """
    namespace = {"__name__": name, "__file__": path, "__package__": package}
    with open(path) as source_file:
        exec(source_file.read(), namespace)
    result = _Namespace()
    for key in namespace:
        setattr(result, key, namespace[key])
    return result


def run_all(root=".", libraries=None):
    """Discover and run all cross-runtime unit tests, returning a shell exit code.

    *root* is the workspace root directory, defaulting to the current
    working directory.

    *libraries* is an optional list of library names to include.
    """
    setup_source_paths(root)

    test_files = discover_tests(root, libraries=libraries)
    if not test_files:
        print("NO TESTS FOUND")
        return 0

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
        result = run_module(test_mod)
        if result != 0:
            total_failed += 1

    if skipped:
        print(f"Skipped {skipped} file(s) (import errors, likely pytest-only)")

    return 1 if total_failed else 0

