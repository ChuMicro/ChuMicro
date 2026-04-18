"""Tests for cross-runtime test discovery and orchestration."""


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
# discover_tests
# ---------------------------------------------------------------------------


def test_discover_tests_finds_test_files(tmp_path):
    """Test files matching test_*.py should be discovered."""
    root = str(tmp_path)
    _make_library(root, "mylib", ["test_one.py", "test_two.py"])

    tests = discovery.discover_tests(root)

    assert len(tests) == 2
    assert any(test_path.endswith("test_one.py") for test_path in tests)
    assert any(test_path.endswith("test_two.py") for test_path in tests)


def test_discover_tests_ignores_non_test_files(tmp_path):
    """Files not matching test_*.py should be skipped."""
    root = str(tmp_path)
    _make_library(root, "mylib", ["test_ok.py"])
    # Add a non-test file.
    conftest = os.path.join(root, "libraries", "mylib", "tests", "conftest.py")
    with open(conftest, "w") as file:
        file.write("")

    tests = discovery.discover_tests(root)

    assert len(tests) == 1
    assert tests[0].endswith("test_ok.py")


def test_discover_tests_empty_when_no_libraries(tmp_path):
    """An empty workspace should yield no tests."""
    assert discovery.discover_tests(str(tmp_path)) == []


def test_discover_tests_filters_by_library_name(tmp_path):
    """Only libraries in the filter list should be included."""
    root = str(tmp_path)
    _make_library(root, "alpha", ["test_alpha.py"])
    _make_library(root, "beta", ["test_beta.py"])

    tests = discovery.discover_tests(root, libraries=["alpha"])

    assert len(tests) == 1
    assert tests[0].endswith("test_alpha.py")


def test_discover_tests_skips_pytest_only_files(tmp_path):
    """Files ending in _pytest.py should be excluded from cross-runtime discovery."""
    root = str(tmp_path)
    _make_library(root, "mylib", ["test_core.py", "test_core_pytest.py"])

    tests = discovery.discover_tests(root)

    assert len(tests) == 1
    assert tests[0].endswith("test_core.py")


# ---------------------------------------------------------------------------
# setup_source_paths
# ---------------------------------------------------------------------------


def test_setup_source_paths_adds_roots_to_sys_path(tmp_path):
    """Discovered source roots should be added to the front of sys.path."""
    root = str(tmp_path)
    _make_library(root, "mylib")
    expected = f"{root}/libraries/mylib/src"

    # Save and restore sys.path so that entries injected by
    # setup_source_paths / run_all don't leak into other tests.
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


# ---------------------------------------------------------------------------
# run_all
# ---------------------------------------------------------------------------


def test_run_all_returns_zero_when_no_tests(tmp_path, capsys):
    """An empty workspace should pass with a 'NO TESTS FOUND' message."""
    root = str(tmp_path)
    # Create library structure with no test files.
    os.makedirs(os.path.join(root, "libraries"))

    original_path = sys.path.copy()
    try:
        result = discovery.run_all(root)
    finally:
        sys.path[:] = original_path

    assert result == 0
    assert "NO TESTS FOUND" in capsys.readouterr().out


def test_run_all_runs_discovered_tests(tmp_path, capsys):
    """run_all should execute discovered test files and report results."""
    root = str(tmp_path)
    _make_library(root, "demo", ["test_demo.py"])
    # Write a real passing test.
    test_file = os.path.join(root, "libraries", "demo", "tests", "test_demo.py")
    with open(test_file, "w") as file:
        file.write("def test_pass(): assert True\n")

    original_path = sys.path.copy()
    try:
        result = discovery.run_all(root)
    finally:
        sys.path[:] = original_path

    assert result == 0
    output = capsys.readouterr().out
    assert "PASS test_pass" in output


def test_run_all_skips_import_errors(tmp_path, capsys):
    """Files that fail to import should be skipped, not cause a failure."""
    root = str(tmp_path)
    _make_library(root, "broken", ["test_broken.py"])
    test_file = os.path.join(root, "libraries", "broken", "tests", "test_broken.py")
    with open(test_file, "w") as file:
        file.write("import nonexistent_module_xyz\n")

    original_path = sys.path.copy()
    try:
        result = discovery.run_all(root)
    finally:
        sys.path[:] = original_path

    assert result == 0
    output = capsys.readouterr().out
    assert "SKIP" in output
    assert "Skipped 1 file(s)" in output


def test_run_all_reports_load_errors(tmp_path, capsys):
    """Files that raise non-ImportError during load should be reported as errors."""
    root = str(tmp_path)
    _make_library(root, "bad", ["test_bad.py"])
    test_file = os.path.join(root, "libraries", "bad", "tests", "test_bad.py")
    with open(test_file, "w") as file:
        file.write("raise RuntimeError('load boom')\n")

    original_path = sys.path.copy()
    try:
        result = discovery.run_all(root)
    finally:
        sys.path[:] = original_path

    assert result == 1
    output = capsys.readouterr().out
    assert "ERROR loading" in output


def test_run_all_counts_failed_test_modules(tmp_path, capsys):
    """run_all should return 1 when a test module contains a failing test."""
    root = str(tmp_path)
    _make_library(root, "failing", ["test_fail.py"])
    test_file = os.path.join(root, "libraries", "failing", "tests", "test_fail.py")
    with open(test_file, "w") as file:
        file.write("def test_boom(): raise AssertionError('nope')\n")

    original_path = sys.path.copy()
    try:
        result = discovery.run_all(root)
    finally:
        sys.path[:] = original_path

    assert result == 1
    output = capsys.readouterr().out
    assert "FAIL test_boom" in output
