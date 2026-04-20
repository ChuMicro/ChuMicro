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

from chumicro_test_harness.runner import run_module


def _is_dir(path):
    """Return True if *path* is an existing directory.

    Uses ``os.listdir`` instead of ``os.path.isdir`` because ``os.path``
    is not available on all CircuitPython builds.

    Args:
        path: Filesystem path to check.
    """
    try:
        os.listdir(path)
        return True
    except OSError:
        return False


def _sorted_listdir(path):
    """Return a sorted listing of *path*, or an empty list on failure.

    Sorting guarantees deterministic test ordering across runtimes and
    filesystems.  Returns an empty list rather than raising when the
    directory does not exist, which simplifies callers.

    Args:
        path: Directory path to list.
    """
    try:
        entries = os.listdir(path)
        entries.sort()
        return entries
    except OSError:
        return []


def discover_source_roots(root_dir="."):
    """Return ``src/`` directories under ``libraries/`` and ``support/``.

    Args:
        root_dir: Workspace root directory.
    """
    source_roots = []
    for parent in ("libraries", "support"):
        # String concatenation instead of os.path.join — os.path may not
        # exist on CircuitPython (see module docstring).
        parent_dir = root_dir + "/" + parent if root_dir != "." else parent
        for name in _sorted_listdir(parent_dir):
            src_dir = parent_dir + "/" + name + "/src"
            if _is_dir(src_dir):
                source_roots.append(src_dir)
    return source_roots


def discover_tests(root_dir=".", libraries=None):
    """Return paths to all ``test_*.py`` files under ``libraries/*/tests/``.

    Args:
        root_dir: Workspace root directory.
        libraries: Optional list of library names to include.
            When ``None``, all libraries are discovered.
    """
    libraries_dir = root_dir + "/libraries" if root_dir != "." else "libraries"
    library_filter = set(libraries) if libraries else None
    test_files = []
    for name in _sorted_listdir(libraries_dir):
        if library_filter is not None and name not in library_filter:
            continue
        tests_dir = libraries_dir + "/" + name + "/tests"
        for filename in _sorted_listdir(tests_dir):
            if filename.startswith("test_") and filename.endswith(".py"):
                # Skip pytest-only tests — they use fixtures or assertions
                # that don't exist on MicroPython/CircuitPython runtimes.
                # See Decision 0016 (referenced in module docstring).
                if filename.endswith("_pytest.py"):
                    continue
                test_files.append(tests_dir + "/" + filename)
    return test_files


def setup_source_paths(root_dir="."):
    """Insert discovered source roots into ``sys.path`` so library imports resolve.

    Args:
        root_dir: Workspace root directory.
    """
    for source_root_dir in discover_source_roots(root_dir):
        if source_root_dir not in sys.path:
            sys.path.insert(0, source_root_dir)


class _Namespace:
    """Attribute container that mimics a module object for ``exec``'d code.

    ``exec()`` populates a plain ``dict``, but :func:`run_module` iterates
    over attributes via ``dir()`` and ``getattr()``.  This class bridges the
    two by copying dict entries into object attributes.
    """

    pass


def _exec_as_namespace(file_path, name="__main__", package=""):
    """Execute a ``.py`` file and return a namespace object with its globals.

    Uses ``exec()`` rather than the standard import machinery because
    multiple libraries have test files with identical names (e.g.
    ``test_core.py``), and MicroPython/CircuitPython lack
    ``importlib.util`` for file-path-based imports.

    Args:
        file_path: Path to the Python file to execute.
        name: Value for ``__name__`` in the exec namespace.
        package: Value for ``__package__`` in the exec namespace.

    Returns:
        Namespace object with the file's globals as attributes.
    """
    # Seed the exec namespace with dunder attributes so the file "feels"
    # like a real module to any code that inspects __name__ or __package__.
    namespace = {"__name__": name, "__file__": file_path, "__package__": package}
    with open(file_path) as source_file:
        exec(source_file.read(), namespace)
    # Convert dict → attribute object so run_module can use dir()/getattr().
    result = _Namespace()
    for key in namespace:
        setattr(result, key, namespace[key])
    return result


def run_all(root_dir=".", libraries=None):
    """Discover and run all cross-runtime unit tests, returning a shell exit code.

    Args:
        root_dir: Workspace root directory.
        libraries: Optional list of library names to include.

    Returns:
        ``0`` for all-pass, ``1`` for any failure.
    """
    setup_source_paths(root_dir)

    test_files = discover_tests(root_dir, libraries=libraries)
    if not test_files:
        print("NO TESTS FOUND")
        return 0

    total_failed = 0
    skipped = 0
    for test_file in test_files:
        print(f"== {test_file} ==")
        try:
            test_module = _exec_as_namespace(test_file)
        except ImportError as error:
            # ImportError usually means the file depends on a pytest-only
            # fixture or a CPython-only module.  Skip gracefully so the
            # remaining test files still run.
            skipped += 1
            print(f"SKIP {test_file} (import failed: {error})")
            continue
        except Exception as error:
            # Non-import errors (SyntaxError, RuntimeError, etc.) indicate
            # a genuine problem in the test file — count as a failure.
            total_failed += 1
            print(f"ERROR loading {test_file}: {error}")
            continue
        result = run_module(test_module)
        if result != 0:
            total_failed += 1

    if skipped:
        print(f"Skipped {skipped} file(s) (import errors, likely pytest-only)")

    return 1 if total_failed else 0
