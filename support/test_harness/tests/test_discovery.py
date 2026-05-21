"""Tests for cross-runtime test discovery and worker-side execution."""


import os
import sys

from chumicro_test_harness import discovery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_library(root: str, name: str, test_files: list[str] | None = None):
    """Create a minimal library layout under *root*/libraries/*name*."""
    source_dir = os.path.join(root, "libraries", name, "src", f"chumicro_{name}")
    os.makedirs(source_dir, exist_ok=True)
    # Create a minimal __init__.py so the package is importable.
    with open(os.path.join(source_dir, "__init__.py"), "w") as file:
        file.write("")

    if test_files:
        tests_dir = os.path.join(root, "libraries", name, "tests")
        os.makedirs(tests_dir, exist_ok=True)
        for test_file in test_files:
            with open(os.path.join(tests_dir, test_file), "w") as file:
                file.write("def test_placeholder(): pass\n")


def _make_support(root: str, name: str):
    """Create a minimal support package layout under *root*/support/*name*."""
    source_dir = os.path.join(root, "support", name, "src", f"chumicro_{name}")
    os.makedirs(source_dir, exist_ok=True)
    with open(os.path.join(source_dir, "__init__.py"), "w") as file:
        file.write("")


# ---------------------------------------------------------------------------
# discover_source_roots
# ---------------------------------------------------------------------------


def test_discover_source_roots_finds_library_and_support_source(tmp_path):
    """Source roots from both libraries/ and support/ should be discovered."""
    root = str(tmp_path)
    _make_library(root, "alpha")
    _make_support(root, "beta")

    roots = discovery.discover_source_roots(root)

    assert f"{root}/libraries/alpha/src" in roots
    assert f"{root}/support/beta/src" in roots


def test_discover_source_roots_ignores_dirs_without_source(tmp_path):
    """Directories without a src/ subdirectory should be skipped."""
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "libraries", "nosrc"))

    assert discovery.discover_source_roots(root) == []


def test_discover_source_roots_returns_sorted(tmp_path):
    """Source roots should be sorted within each parent group."""
    root = str(tmp_path)
    _make_library(root, "zebra")
    _make_library(root, "alpha")

    roots = discovery.discover_source_roots(root)
    lib_roots = [path for path in roots if "/libraries/" in path]

    assert lib_roots == sorted(lib_roots)


# ---------------------------------------------------------------------------
# setup_source_paths
# ---------------------------------------------------------------------------


def test_setup_source_paths_adds_roots_to_sys_path(tmp_path):
    """Discovered source roots should be added to the front of sys.path."""
    root = str(tmp_path)
    _make_library(root, "mylib")
    expected = f"{root}/libraries/mylib/src"

    original_path = sys.path.copy()
    try:
        discovery.setup_source_paths(root)
        assert expected in sys.path
    finally:
        sys.path[:] = original_path


def test_setup_source_paths_does_not_duplicate(tmp_path):
    """Calling setup twice should not add duplicate entries."""
    root = str(tmp_path)
    _make_library(root, "mylib")
    expected = f"{root}/libraries/mylib/src"

    original_path = sys.path.copy()
    try:
        discovery.setup_source_paths(root)
        discovery.setup_source_paths(root)
        assert sys.path.count(expected) == 1
    finally:
        sys.path[:] = original_path


# ---------------------------------------------------------------------------
# _exec_as_namespace
# ---------------------------------------------------------------------------


def test_exec_as_namespace_returns_namespace_with_globals(tmp_path):
    """Exec'd globals should be accessible as attributes on the namespace."""
    script = tmp_path / "sample.py"
    script.write_text("VALUE = 42\ndef helper(): return 'ok'\n")

    ns = discovery._exec_as_namespace(str(script))

    assert ns.VALUE == 42
    assert ns.helper() == "ok"


def test_exec_as_namespace_sets_dunder_name(tmp_path):
    """The namespace should reflect the provided __name__ and __package__."""
    script = tmp_path / "sample.py"
    script.write_text("pass\n")

    ns = discovery._exec_as_namespace(str(script), name="mymod", package="mypkg")

    assert ns.__name__ == "mymod"
    assert ns.__package__ == "mypkg"


def test_exec_chunked_matches_whole_file_semantics(tmp_path):
    """Chunked exec yields a namespace identical to the whole-file path.

    A preamble import + helper used by a later class, a decorated
    function, and cross-statement name references must all resolve via
    the shared globals exactly as a single exec would.
    """
    source = (
        "import math\n"
        "\n"
        "BASE = 10\n"
        "\n"
        "def _double(value):\n"
        "    return value * 2\n"
        "\n"
        "def deco(func):\n"
        "    func.tagged = True\n"
        "    return func\n"
        "\n"
        "@deco\n"
        "def tagged_fn():\n"
        "    return 'tagged'\n"
        "\n"
        "class TestThing:\n"
        "    def test_uses_preamble(self):\n"
        "        return _double(BASE) + int(math.sqrt(16))\n"
    )
    script = tmp_path / "mod.py"
    script.write_text(source)

    whole = discovery._exec_as_namespace(str(script))
    # Decorator-aware boundaries (1-based): import, BASE, _double, deco,
    # the @deco line, class.
    chunked = discovery._exec_as_namespace(
        str(script), chunk_boundaries=[1, 3, 5, 8, 12, 16]
    )

    assert chunked.BASE == whole.BASE == 10
    assert chunked.tagged_fn.tagged is True
    assert chunked.TestThing().test_uses_preamble() == 24
    assert whole.TestThing().test_uses_preamble() == 24


def test_exec_chunked_preserves_line_numbers(tmp_path):
    """A failure in a late chunk reports its real source line.

    The newline left-pad must keep tracebacks pointing at the original
    file line, not the chunk-relative line.
    """
    source = (
        "X = 1\n"          # line 1
        "\n"                # line 2
        "def boom():\n"     # line 3
        "    raise RuntimeError('kaboom')\n"  # line 4
    )
    script = tmp_path / "mod.py"
    script.write_text(source)

    ns = discovery._exec_as_namespace(str(script), chunk_boundaries=[1, 3])
    try:
        ns.boom()
    except RuntimeError as error:
        tb = error.__traceback__
        while tb.tb_next is not None:
            tb = tb.tb_next
        assert tb.tb_lineno == 4
    else:  # pragma: no cover - the call always raises
        raise AssertionError("expected RuntimeError")


# ---------------------------------------------------------------------------
# run_one_file: the worker entry point used by the pytest plugin's
# UnixPortBackend (spawns one subprocess per test file).
# ---------------------------------------------------------------------------


def test_run_one_file_runs_passing_test(tmp_path, capsys):
    """run_one_file should execute one file in-process and return 0 on pass."""
    root = str(tmp_path)
    _make_library(root, "demo", ["test_demo.py"])
    test_file = os.path.join(root, "libraries", "demo", "tests", "test_demo.py")
    with open(test_file, "w") as file:
        file.write("def test_pass(): assert True\n")

    original_path = sys.path.copy()
    try:
        result = discovery.run_one_file(test_file, root_dir=root)
    finally:
        sys.path[:] = original_path

    assert result == 0
    output = capsys.readouterr().out
    assert "PASS test_pass" in output


def test_run_one_file_fails_on_import_errors(tmp_path, capsys):
    """run_one_file returns 1 and prints a FAIL line when the file fails to import.

    The FAIL message must name ``__chumicro_runtimes__`` so a reader of
    the output knows which marker to add: a cross-runtime test file that
    imports pytest / unittest / tracemalloc must be declared CPython-only,
    not silently dropped from MP / CP runs.
    """
    root = str(tmp_path)
    _make_library(root, "broken", ["test_broken.py"])
    test_file = os.path.join(
        root, "libraries", "broken", "tests", "test_broken.py",
    )
    with open(test_file, "w") as file:
        file.write("import nonexistent_module_xyz\n")

    original_path = sys.path.copy()
    try:
        result = discovery.run_one_file(test_file, root_dir=root)
    finally:
        sys.path[:] = original_path

    assert result == 1
    output = capsys.readouterr().out
    assert "FAIL" in output
    assert "import failed" in output
    assert "__chumicro_runtimes__" in output


def test_run_one_file_reports_load_errors(tmp_path, capsys):
    """run_one_file returns 1 on non-ImportError load failures."""
    root = str(tmp_path)
    _make_library(root, "bad", ["test_bad.py"])
    test_file = os.path.join(root, "libraries", "bad", "tests", "test_bad.py")
    with open(test_file, "w") as file:
        file.write("raise RuntimeError('load boom')\n")

    original_path = sys.path.copy()
    try:
        result = discovery.run_one_file(test_file, root_dir=root)
    finally:
        sys.path[:] = original_path

    assert result == 1
    assert "ERROR loading" in capsys.readouterr().out
