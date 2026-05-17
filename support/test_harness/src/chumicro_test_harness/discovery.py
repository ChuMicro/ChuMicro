"""Cross-runtime test discovery — worker-side helpers.

Used by :mod:`support.test_harness.run_cross_runtime` (the worker
entry point) and by :mod:`chumicro_pytest_device.plugin` (the host
side that spawns the workers).  Manager-mode discovery — walking
``libraries/*/tests/`` and orchestrating one subprocess per file —
moved into the pytest plugin's collection layer; the only thing
this module owns now is single-file execution.

Avoids ``os.path`` (unavailable on some CircuitPython builds) and
keeps the import footprint minimal so :func:`run_one_file` can
execute under CPython, MicroPython unix-port, and CircuitPython
unix-port.

A file that fails to import is a hard FAIL, not a silent SKIP —
files that pull in pytest / unittest / tracemalloc must either be
converted to cross-runtime or declare ``__chumicro_runtimes__ =
("cpython",)`` (CPython-only lane).  A file that drives
runtime-specific source through host fakes declares
``__chumicro_host_only__ = True`` instead.
"""

import os
import sys

from chumicro_test_harness.runner import run_module

try:
    import gc as _gc
except ImportError:  # pragma: no cover - gc may be absent on some CPython configs.
    _gc = None


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


def _exec_chunked(source, boundaries, namespace):
    """Exec *source* in top-level-statement chunks into *namespace*.

    Splitting a module at top-level statement boundaries and exec'ing
    each piece into the *same* globals dict, in source order, is
    semantically identical to exec'ing the whole module — name
    resolution goes through the shared dict either way.  What it buys
    is a bounded *compile* transient: MicroPython / CircuitPython
    compile the whole ``exec`` argument at once, and that peak (not the
    resulting objects) is what exhausts a 256 KB board on a large
    class-organized test module.  Chunking caps the peak at the
    largest single top-level statement.

    Each chunk is left-padded with newlines so its statements keep
    their original line numbers — tracebacks still point at the real
    source line.

    Args:
        source: Full file source text.
        boundaries: 1-based start lines of top-level statements
            (decorator-aware), computed host-side via ``ast``.
        namespace: The shared exec globals dict.
    """
    lines = source.split("\n")
    # Line 1 anchors the module preamble (docstring / imports before
    # the first statement); the rest are statement starts.  Built with
    # plain list ops — MicroPython / CircuitPython lack PEP 448 set
    # unpacking, and this module runs on-device.
    candidates = [1]
    for line in boundaries:
        if line > 1:
            candidates.append(line)
    starts = []
    for value in sorted(candidates):
        if not starts or starts[-1] != value:
            starts.append(value)
    for index in range(len(starts)):
        begin = starts[index] - 1
        end = starts[index + 1] - 1 if index + 1 < len(starts) else len(lines)
        chunk = "\n" * begin + "\n".join(lines[begin:end])
        if chunk.strip():
            exec(chunk, namespace)
        if _gc is not None:
            _gc.collect()


def _exec_as_namespace(file_path, name="__main__", package="", chunk_boundaries=None):
    """Execute a ``.py`` file and return a namespace object with its globals.

    Uses ``exec()`` rather than the standard import machinery because
    multiple libraries have test files with identical names (e.g.
    ``test_core.py``), and MicroPython/CircuitPython lack
    ``importlib.util`` for file-path-based imports.

    Args:
        file_path: Path to the Python file to execute.
        name: Value for ``__name__`` in the exec namespace.
        package: Value for ``__package__`` in the exec namespace.
        chunk_boundaries: Optional 1-based top-level statement start
            lines (computed host-side via ``ast``).  When provided the
            file is exec'd in per-statement chunks to bound the compile
            transient on RAM-constrained boards; ``None`` keeps the
            single whole-file ``exec`` (CPython / unix-port, where RAM
            is ample and one compile is faster).

    Returns:
        Namespace object with the file's globals as attributes.
    """
    # Seed the exec namespace with dunder attributes so the file "feels"
    # like a real module to any code that inspects __name__ or __package__.
    namespace = {"__name__": name, "__file__": file_path, "__package__": package}
    with open(file_path) as source_file:
        source = source_file.read()
    if chunk_boundaries:
        _exec_chunked(source, chunk_boundaries, namespace)
    else:
        exec(source, namespace)
    # Convert dict → attribute object so run_module can use dir()/getattr().
    result = _Namespace()
    for key in namespace:
        setattr(result, key, namespace[key])
    return result


def run_one_file(test_file, root_dir="."):
    """Run a single test file in the current process; return shell exit code.

    An ImportError here is a hard FAIL, not a silent SKIP — the offending
    file must either be converted to cross-runtime or declare
    ``__chumicro_runtimes__ = ("cpython",)`` (or
    ``__chumicro_host_only__ = True`` if it drives runtime-specific
    source through host fakes).
    """
    setup_source_paths(root_dir)
    print(f"== {test_file} ==")
    try:
        test_module = _exec_as_namespace(test_file)
    except ImportError as error:
        print(
            f"FAIL {test_file} — import failed: {error} "
            f"(declare __chumicro_runtimes__ = (\"cpython\",) if "
            f"intentionally CPython-only, or __chumicro_host_only__ = "
            f"True if it drives runtime-specific source via host fakes)"
        )
        return 1
    except Exception as error:
        print(f"ERROR loading {test_file}: {error}")
        return 1
    return run_module(test_module)
