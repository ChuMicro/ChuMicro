"""Load and execute a cross-runtime test file in the current process.

Exposes :func:`run_one_file` plus the sys.path bootstrap
(:func:`discover_source_roots`, :func:`setup_source_paths`) and the
``exec``-based module loader the worker path needs. Imported by the
``run_cross_runtime.py`` worker script and by the
``chumicro_pytest_device`` plugin's collection layer.

Avoids ``os.path`` because some CircuitPython builds omit it. Keeps the
import footprint minimal so :func:`run_one_file` works under CPython,
MicroPython unix-port, CircuitPython unix-port, and on real devices.
"""

import gc
import os
import sys

from chumicro_test_harness.runner import run_module


def _is_dir(path):
    """Return True if *path* is an existing directory.

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
        # String concatenation instead of os.path.join: os.path may not
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
    semantically identical to exec'ing the whole module. Name
    resolution goes through the shared dict either way.  What it buys
    is a bounded *compile* transient: MicroPython / CircuitPython
    compile the whole ``exec`` argument at once, and that peak (not the
    resulting objects) is what exhausts a 256 KB board on a large
    class-organized test module.  Chunking caps the peak at the
    largest single top-level statement.

    Each chunk is left-padded with newlines so its statements keep
    their original line numbers. Tracebacks still point at the real
    source line.

    Args:
        source: Full file source text.
        boundaries: 1-based start lines of top-level statements
            (decorator-aware), computed host-side via ``ast``.
        namespace: The shared exec globals dict.
    """
    lines = source.split("\n")
    # Line 1 anchors the module preamble (docstring / imports before
    # the first statement). The rest are statement starts.  Built with
    # plain list ops: MicroPython / CircuitPython lack PEP 448 set
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
        gc.collect()


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
            transient on RAM-constrained boards. ``None`` keeps the
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
    # Copy entries into an attribute container so run_module can use dir() and getattr().
    result = _Namespace()
    for key in namespace:
        setattr(result, key, namespace[key])
    return result


def _parent_dir(file_path):
    """Return the directory part of *file_path*, or ``"."`` if it has none.

    Splits on the last ``/`` instead of using ``os.path.dirname`` because
    some CircuitPython builds omit ``os.path`` (see module docstring).
    A path with no slash (a bare filename) yields ``"."``.

    Args:
        file_path: Path to a file.
    """
    head, _, _ = file_path.rpartition("/")
    return head if head else "."


def run_one_file(test_file, root_dir=".", chunk_boundaries=None):
    """Set up sys.path, exec the file, run its tests, return 0/1 exit code.

    Inserts the test file's own directory on ``sys.path`` before exec so
    a ``from _socket_stubs import ...`` line (pulling in an
    underscore-prefixed sibling helper module that lives next to the
    test file) resolves on the host and unix-port runs.  On a device the
    sibling is staged into the import root instead.

    Returns 1 for ImportError during load (with a FAIL line whose
    message names the runtime markers the file needs to declare), for
    non-ImportError load failures (ERROR line), or for any test failure
    inside the file. Returns 0 only when every test passes.
    """
    setup_source_paths(root_dir)
    test_dir = _parent_dir(test_file)
    if test_dir not in sys.path:
        sys.path.insert(0, test_dir)
    print(f"== {test_file} ==")
    try:
        test_module = _exec_as_namespace(test_file, chunk_boundaries=chunk_boundaries)
    except ImportError as error:
        print(
            f"FAIL {test_file}: import failed: {error} "
            f"(declare __chumicro_runtimes__ = (\"cpython\",) if "
            f"intentionally CPython-only, or __chumicro_host_only__ = "
            f"True if it drives runtime-specific source via host fakes)"
        )
        return 1
    except Exception as error:
        print(f"ERROR loading {test_file}: {error}")
        return 1
    return run_module(test_module)
