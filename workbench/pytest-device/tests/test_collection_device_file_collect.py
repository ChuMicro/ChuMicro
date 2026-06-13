"""End-to-end pytest sessions driving DeviceTestFile.collect on unix-port.

Each test builds a synthetic workspace in a pytester tmp dir whose
"runtime binary" is the host Python and whose harness worker is a stub
script printing PASS / FAIL / SKIP lines, then runs a real in-process
pytest session against it.  This exercises the collect paths a direct
unit test cannot reach: per-runtime item synthesis, suffix naming under
two targets, the prepare / run-overhead / per-test item trio, and the
batched runtest result lookup.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

pytest_plugins = ("pytester",)


#: Harness-worker stand-in.  Scans the test file it is handed for
#: ``def test_*`` names and prints one harness line per test: names
#: containing ``fails_on_device`` FAIL, ``skips_on_device`` SKIP,
#: ``vanishes`` print nothing (simulating a test lost before the
#: harness), everything else PASSes.
_STUB_WORKER = textwrap.dedent(
    """\
    import re
    import sys

    test_file = sys.argv[-1]
    with open(test_file) as handle:
        source = handle.read()
    names = re.findall(r"^def (test_\\w+)", source, re.MULTILINE)
    failed = 0
    for name in names:
        if "vanishes" in name:
            continue
        if "fails_on_device" in name:
            print(f"FAIL {name} (0.01s)")
            failed += 1
        elif "skips_on_device" in name:
            print(f"SKIP {name} (not supported here)")
        else:
            print(f"PASS {name} (0.01s)")
    print(f"SUMMARY total={len(names)} failed={failed} time=0.05s")
    """
)


def _build_workspace(root: Path) -> None:
    """Lay out the harness worker and one ``demo`` library under *root*."""
    worker = root / "support" / "test_harness" / "run_cross_runtime.py"
    worker.parent.mkdir(parents=True)
    worker.write_text(_STUB_WORKER)
    _add_library(root, "demo")


def _add_library(
    root: Path, name: str, *, platforms: tuple[str, ...] | None = None,
) -> Path:
    """Create ``libraries/<name>`` with a src package and empty tests dir."""
    library_dir = root / "libraries" / name
    source_dir = library_dir / "src" / f"chumicro_{name}"
    source_dir.mkdir(parents=True)
    (source_dir / "__init__.py").write_text("")
    (library_dir / "tests").mkdir()
    pyproject_lines = [
        "[project]",
        f'name = "chumicro-{name}"',
        'version = "0.0.1"',
    ]
    if platforms is not None:
        platform_list = ", ".join(f'"{platform}"' for platform in platforms)
        pyproject_lines += ["[tool.chumicro]", f"platforms = [{platform_list}]"]
    (library_dir / "pyproject.toml").write_text(
        "\n".join(pyproject_lines) + "\n",
    )
    return library_dir


def _unix_port_args(*runtimes: str) -> list[str]:
    """CLI args selecting the unix-port backend with stub binaries."""
    selection = runtimes[0] if len(runtimes) == 1 else "both"
    return [
        "--target", "unix-port",
        "--runtime", selection,
        "--micropython-binary", sys.executable,
        "--circuitpython-binary", sys.executable,
        "-p", "no:cacheprovider",
    ]


def _start_session(pytester) -> Path:
    """Pin the rootdir and build the synthetic workspace."""
    pytester.makeini("[pytest]\n")
    _build_workspace(pytester.path)
    return pytester.path


class TestSingleRuntimeCollect:
    """One unix-port target: unsuffixed names, prepare + run + test items."""

    def test_green_file_yields_prepare_run_and_test_passes(
        self, pytester,
    ) -> None:
        """Two passing tests produce four green items for one runtime."""
        root = _start_session(pytester)
        test_file = root / "libraries" / "demo" / "tests" / "test_demo.py"
        test_file.write_text(
            "def test_alpha():\n    pass\n\n"
            "def test_beta():\n    pass\n",
        )

        result = pytester.runpytest(
            str(test_file), *_unix_port_args("micropython"),
        )

        # Prepare + run-overhead + test_alpha + test_beta.
        result.assert_outcomes(passed=4)

    def test_fail_skip_and_missing_results_map_to_pytest_outcomes(
        self, pytester,
    ) -> None:
        """FAIL lines fail, SKIP lines skip, absent results fail loudly."""
        root = _start_session(pytester)
        test_file = root / "libraries" / "demo" / "tests" / "test_mixed.py"
        test_file.write_text(
            "def test_passes():\n    pass\n\n"
            "def test_fails_on_device():\n    pass\n\n"
            "def test_skips_on_device():\n    pass\n\n"
            "def test_vanishes():\n    pass\n",
        )

        result = pytester.runpytest(
            str(test_file), *_unix_port_args("micropython"),
        )

        # Passed: prepare, run-overhead, test_passes.  Failed: the
        # device-FAIL plus the result that never appeared in harness
        # output.  Skipped: the device-SKIP.
        result.assert_outcomes(passed=3, failed=2, skipped=1)
        result.stdout.fnmatch_lines(["*Device test FAIL: test_fails_on_device*"])
        result.stdout.fnmatch_lines(["*not found in device output*"])

    def test_functional_file_routes_through_the_device_collector(
        self, pytester,
    ) -> None:
        """A functional_tests file is claimed and run via the harness backend."""
        root = _start_session(pytester)
        functional_dir = root / "libraries" / "demo" / "functional_tests"
        functional_dir.mkdir()
        test_file = functional_dir / "test_func.py"
        test_file.write_text("def test_round_trip():\n    pass\n")

        result = pytester.runpytest(
            str(test_file), *_unix_port_args("micropython"),
        )

        result.assert_outcomes(passed=3)


class TestBothRuntimesCollect:
    """Two targets: every item collected per runtime with a name suffix."""

    def test_each_test_collects_once_per_runtime_with_suffix(
        self, pytester,
    ) -> None:
        """Both runtimes double the items and suffix the display names."""
        root = _start_session(pytester)
        test_file = root / "libraries" / "demo" / "tests" / "test_demo.py"
        test_file.write_text(
            "def test_alpha():\n    pass\n\n"
            "def test_beta():\n    pass\n",
        )

        result = pytester.runpytest(
            str(test_file), "-v", *_unix_port_args("micropython", "circuitpython"),
        )

        # (prepare + run + 2 tests) x 2 runtimes.
        result.assert_outcomes(passed=8)
        result.stdout.fnmatch_lines(["*test_alpha*MicroPython*"])
        result.stdout.fnmatch_lines(["*test_alpha*CircuitPython*"])

    def test_runtime_restricted_marker_collects_single_suffixed_target(
        self, pytester,
    ) -> None:
        """A one-runtime marker under a both-runtime session keeps the suffix."""
        root = _start_session(pytester)
        test_file = root / "libraries" / "demo" / "tests" / "test_mp_only.py"
        test_file.write_text(
            '__chumicro_runtimes__ = ("micropython",)\n\n'
            "def test_alpha():\n    pass\n",
        )

        result = pytester.runpytest(
            str(test_file), "-v", *_unix_port_args("micropython", "circuitpython"),
        )

        # One runtime only: prepare + run + one test.
        result.assert_outcomes(passed=3)
        result.stdout.fnmatch_lines(["*test_alpha*MicroPython*"])


class TestMarkerAndPlatformExclusion:
    """Whole-file exclusions: runtime markers and library platform keys."""

    def test_cpython_only_marker_yields_zero_items(self, pytester) -> None:
        """A cpython-only file produces no unix-port items at all."""
        root = _start_session(pytester)
        test_file = root / "libraries" / "demo" / "tests" / "test_cpython.py"
        test_file.write_text(
            '__chumicro_runtimes__ = ("cpython",)\n\n'
            "def test_host_only_logic():\n    pass\n",
        )

        result = pytester.runpytest(
            str(test_file), *_unix_port_args("micropython"),
        )

        result.assert_outcomes()  # nothing collected, nothing run

    def test_non_targeting_library_items_are_deselected(
        self, pytester,
    ) -> None:
        """platforms excluding the runtime deselects that library's items."""
        root = _start_session(pytester)
        cp_only = _add_library(root, "cponly", platforms=("circuitpython",))
        (cp_only / "tests" / "test_cp.py").write_text(
            "def test_cp_thing():\n    pass\n",
        )
        all_runtimes = root / "libraries" / "demo" / "tests" / "test_demo.py"
        all_runtimes.write_text("def test_alpha():\n    pass\n")

        result = pytester.runpytest(
            str(cp_only / "tests" / "test_cp.py"), str(all_runtimes),
            *_unix_port_args("micropython"),
        )

        # cponly's prepare + run + test deselected; demo's trio passes.
        result.assert_outcomes(passed=3, deselected=3)


class TestZeroTestFileGuard:
    """A pytest-style file with no harness-discoverable tests fails collection."""

    def test_unit_file_without_test_functions_is_a_collect_error(
        self, pytester,
    ) -> None:
        """The cross-runtime lane refuses a silently empty test file."""
        root = _start_session(pytester)
        test_file = root / "libraries" / "demo" / "tests" / "test_styleless.py"
        test_file.write_text(
            "import pytest\n\n"
            "@pytest.fixture\n"
            "def helper():\n    return 1\n",
        )

        result = pytester.runpytest(
            str(test_file), *_unix_port_args("micropython"),
        )

        result.assert_outcomes(errors=1)
        result.stdout.fnmatch_lines(["*defines no discoverable tests*"])
