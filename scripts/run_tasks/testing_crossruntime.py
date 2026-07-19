"""Cross-runtime unix-port test lanes: ``test-micropython``,
``test-circuitpython``, ``test-all-runtimes``."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from repo_layout import ROOT, discover_package_dirs, pythonpath_environment
from shared import stream_subprocess

from run_tasks._dispatch import (
    _DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
    PYTHON,
    _emit,
    _pick_dispatcher,
    _run_parallel_phases,
    _Sink,
)
from run_tasks.testing_cpython import (
    _FilteringSink,
    _format_pytest_phase_summary,
    _PytestOutputFilter,
    _PytestRunResult,
    _selected_library_dirs,
    test_cpython,
)


def _pytest_unix_port_command(
    runtime: str,
    binary: str | None,
    package_dirs: list[Path] | None,
    *,
    slow_test_threshold_s: float,
) -> list[str]:
    """Build the ``pytest ... --target unix-port --runtime <X>`` invocation.

    Selects the same set of publishable libraries the parallel-phase
    dispatcher used to pass directly to the compatibility script.  The
    plugin handles platform filtering ([tool.chumicro].platforms) and
    skips per-test cases for libraries that don't target *runtime*.
    """
    libraries_root = ROOT / "libraries"
    library_dirs = _selected_library_dirs(package_dirs)
    if library_dirs:
        paths = [
            str(library_dir / "tests")
            for library_dir in library_dirs
            if (library_dir / "tests").is_dir()
        ]
    else:
        paths = [str(libraries_root)]
    command = [
        PYTHON, "-m", "pytest", *paths,
        "--target", "unix-port",
        "--runtime", runtime,
        "--no-cov",
        "--durations=0", f"--durations-min={slow_test_threshold_s}",
    ]
    if binary is not None:
        command.extend([f"--{runtime}-binary", binary])
    return command


def _ensure_unix_port_binary(
    runtime: str,
    binary: str | None,
    resolve: Callable[[], str | None],
    prepare_function: Callable[[], int],
    sink: _Sink | None,
) -> int:
    """Resolve or build the unix-port binary, returning a shell exit code.

    Mirrors the auto-prepare-on-first-use behavior the old
    ``_test_runtime_compat`` helper provided: the plugin can't build
    binaries itself, so the CLI wrapper does it before delegating.
    Returns 0 on success, non-zero when preparation failed.
    """
    if binary is not None:
        return 0
    if resolve() is not None:
        return 0
    _emit(
        sink,
        f"{runtime} binary not found.  Preparing unix-port runtime first.",
    )
    prepare_result = prepare_function()
    if prepare_result != 0:
        _emit(sink, f"{runtime} preparation failed.")
        return prepare_result
    if resolve() is None:
        _emit(
            sink,
            f"Preparation completed without the expected binary.  "
            f"Pass --{runtime}-binary <path> and retry.",
        )
        return 1
    return 0


def _run_unix_port_pytest(
    runtime: str,
    command: list[str],
    sink: _Sink | None,
    slow_test_threshold_s: float,
) -> int:
    """Run a single unix-port pytest invocation through the output filter.

    Captures the per-runtime ``=== N passed ... in Xs ===`` line plus
    pytest's ``slowest durations`` block into a
    :class:`_PytestRunResult` so the runner can emit a rolled-up
    ``test-<runtime>: N passed in Xs`` summary (and a warn-only
    ``SLOW`` notice for tests crossing *slow_test_threshold_s*) at
    phase completion, regardless of whether the caller piped output
    through a sink or directly to stdout.
    """
    filter_state = _PytestOutputFilter()
    if sink is not None:
        sink.line(f"+ {' '.join(command)}")
        wrapped = _FilteringSink(sink, filter_state)
        exit_code, _ = stream_subprocess(
            command,
            on_line=wrapped.line,
            environment=pythonpath_environment(),
        )
    else:
        print(f"+ {' '.join(command)}")
        def consume_line(text: str) -> None:
            if not filter_state.consume(text):
                print(text)
        exit_code, _ = stream_subprocess(
            command,
            on_line=consume_line,
            environment=pythonpath_environment(),
        )

    result = _PytestRunResult.build(f"test-{runtime}", exit_code, filter_state)
    for line in _format_pytest_phase_summary(
        f"test-{runtime}",
        [result],
        slow_threshold_s=slow_test_threshold_s,
    ):
        _emit(sink, line)
    return exit_code


def test_micropython(
    binary: str | None = None,
    package_dirs: list[Path] | None = None,
    *,
    sink: _Sink | None = None,
    slow_test_threshold_s: float = _DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
) -> int:
    """Run unix-port unit tests under the MicroPython binary.

    Thin wrapper that auto-prepares the binary on first use, then
    delegates to ``pytest ... --target unix-port --runtime micropython``.
    Platform filtering happens inside ``chumicro-pytest-device`` based
    on each library's ``[tool.chumicro].platforms``.  Per-test
    durations crossing *slow_test_threshold_s* surface as warn-only
    ``SLOW`` notices after the rolled-up phase summary.
    """
    from prepare_micropython import prepare_micropython
    from shared import resolve_micropython_binary

    prep_result = _ensure_unix_port_binary(
        "micropython", binary,
        lambda: resolve_micropython_binary(binary), prepare_micropython, sink,
    )
    if prep_result != 0:
        return prep_result
    command = _pytest_unix_port_command(
        "micropython", binary, package_dirs,
        slow_test_threshold_s=slow_test_threshold_s,
    )
    return _run_unix_port_pytest(
        "micropython", command, sink, slow_test_threshold_s,
    )


def test_circuitpython(
    binary: str | None = None,
    package_dirs: list[Path] | None = None,
    *,
    sink: _Sink | None = None,
    slow_test_threshold_s: float = _DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
) -> int:
    """Run unix-port unit tests under the CircuitPython binary.

    Thin wrapper: see :func:`test_micropython` for the shape.
    """
    from prepare_circuitpython import prepare_circuitpython
    from shared import resolve_circuitpython_binary

    prep_result = _ensure_unix_port_binary(
        "circuitpython", binary,
        lambda: resolve_circuitpython_binary(binary), prepare_circuitpython,
        sink,
    )
    if prep_result != 0:
        return prep_result
    command = _pytest_unix_port_command(
        "circuitpython", binary, package_dirs,
        slow_test_threshold_s=slow_test_threshold_s,
    )
    return _run_unix_port_pytest(
        "circuitpython", command, sink, slow_test_threshold_s,
    )


def test_all_runtimes(
    micropython_binary: str | None = None,
    circuitpython_binary: str | None = None,
    package_dirs: list[Path] | None = None,
    *,
    slow_test_threshold_s: float = _DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
) -> int:
    """Run host tests and cross-runtime unit tests across all proven runtimes.

    CPython tests run first (often the source of failures and the
    fastest signal).  The two unix-port compatibility phases then run
    **in parallel** since they're independent subprocess invocations
    against different runtime binaries.  Output is buffered per phase
    and printed when each phase finishes so phase logs don't interleave.
    """
    all_packages = package_dirs if package_dirs is not None else discover_package_dirs()

    print("== test ==")
    cpython_result = test_cpython(all_packages)
    if cpython_result != 0:
        print("Step failed: test")
        return cpython_result

    parallel_phases: tuple[tuple[str, Callable[[_Sink], int]], ...] = (
        (
            "test-micropython",
            lambda sink: test_micropython(
                micropython_binary, package_dirs, sink=sink,
                slow_test_threshold_s=slow_test_threshold_s,
            ),
        ),
        (
            "test-circuitpython",
            lambda sink: test_circuitpython(
                circuitpython_binary, package_dirs, sink=sink,
                slow_test_threshold_s=slow_test_threshold_s,
            ),
        ),
    )
    exit_code, _failing_label, _phase_results = _run_parallel_phases(
        parallel_phases,
        dispatcher=_pick_dispatcher(quiet=False),
    )
    return exit_code


def _add_unix_port_test_args(parser: argparse.ArgumentParser) -> None:
    """Attach the slow-test-threshold flag to a unix-port test subcommand.

    Keeps ``test-micropython`` / ``test-circuitpython`` / ``test-all-
    runtimes`` in lockstep on the threshold knob without re-declaring
    it in three places.
    """
    parser.add_argument(
        "--slow-test-threshold-unix-port", type=float, metavar="SECONDS",
        default=_DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
        help=(
            f"warn-only threshold for surfacing slow unix-port tests "
            f"(default: {_DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT:.1f}s)"
        ),
    )


def register(subparsers, parents):
    """Register the cross-runtime unix-port test subcommands."""
    scope = parents["scope"]
    binary = parents["binary"]
    test_micropython_parser = subparsers.add_parser(
        "test-micropython",
        parents=[scope, binary],
        help="MicroPython cross-runtime unit tests",
    )
    _add_unix_port_test_args(test_micropython_parser)
    test_circuitpython_parser = subparsers.add_parser(
        "test-circuitpython",
        parents=[scope, binary],
        help="CircuitPython cross-runtime unit tests",
    )
    _add_unix_port_test_args(test_circuitpython_parser)
    test_all_runtimes_parser = subparsers.add_parser(
        "test-all-runtimes",
        parents=[scope, binary],
        help="test all packages on CPython + MicroPython + CircuitPython",
    )
    _add_unix_port_test_args(test_all_runtimes_parser)
