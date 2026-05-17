"""Repository-level task runner for humans, agents, and CI.

Usage::

    python scripts/run.py <task> [options]

Run ``python scripts/run.py -h`` to see available tasks.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# Hot-path imports — touched by lint, run_command, ROOT-derived path
# discovery on every invocation.  Heavier imports (check_api,
# docs_deploy, prepare_*, validate_mip_install, verify_examples,
# new_library_scaffold, ide_sync, render_dep_graph,
# shared.install_workspace) are deferred into the task wrappers that
# need them (Bucket 4 #5).  Each of those modules pulls in tomllib /
# yaml / ast walkers / griffe / mike / etc.; eager-loading them
# meant every phase that subprocess-re-invokes ``python scripts/run.py``
# (Decision 0048) paid the full import-time tax even when running a
# task that didn't touch them.
from repo_layout import (
    ROOT,
    coverage_args_for,
    detect_changed_packages,
    discover_doc_dirs,
    discover_library_dirs,
    discover_package_dirs,
    discover_ruff_paths,
    discover_workbench_dirs,
    find_publishable_packages,
    is_ref_reachable,
    pythonpath_environment,
    resolve_scope,
)
from shared import run_command, stream_subprocess

PYTHON = sys.executable


def _default_workers() -> tuple[int, int]:
    """Return ``(phase_workers, package_workers)`` defaults sized for this host.

    Preflight is mostly I/O-bound (pytest startup, subprocess spawning,
    file reads), not CPU-bound, so mild oversubscription is a win.
    Earlier sqrt-based sizing came from when the test phase was 73 s
    and genuinely CPU-contended; the unit-test phases are seconds-scale
    today.  After the per-library fan-out reached test-micropython /
    test-circuitpython (each now ~2.5 s standalone, ~6 s under preflight
    contention with concurrent test-cpython + build + docs), the wall-
    time floor is dominated by whichever single phase loses most to
    cross-phase resource contention — typically ``test (python <ver>)``.

    Sizing rule: run every preflight phase concurrently when cores
    allow (cap at 11 — the total phase count), and let the
    per-package test fan-out hit its diminishing-returns ceiling
    around 8 packages wide.

    Worked examples (benchmarked on a 12-core M-series host, 21
    per-package test runs, preflight wall time):

    ====  =====  =======  ========
    cpu   phase  package  total
    ====  =====  =======  ========
      4    4      4         16
      8    8      6         48
     12   11      8         88
     16   11      8         88
     24   11      8         88
    ====  =====  =======  ========

    Override via ``--phase-workers`` and ``--package-workers``.
    """
    cores = max(2, os.cpu_count() or 4)
    phase = max(2, min(11, cores))
    package = max(2, min(8, cores // 2 + 2))
    return phase, package


_DEFAULT_PHASE_WORKERS, _DEFAULT_PACKAGE_WORKERS = _default_workers()


#: Default cap on concurrent ``preflight`` *phases*.  Each phase is
#: its own ``python scripts/run.py <subcommand>`` subprocess that may
#: itself fan out internally (build / docs, test_cpython via pytest,
#: etc.), so a higher phase-level cap multiplies subprocess count.
#: See :func:`_default_workers` for the host-aware sizing rule and
#: Decision 0048.  Override via ``--phase-workers``.
_DEFAULT_PREFLIGHT_PHASE_PARALLEL_WORKERS = _DEFAULT_PHASE_WORKERS


#: Default cap on concurrent per-package subprocesses for build /
#: docs / test fan-out.  Each task spawns one external process
#: (``python -m build``, ``python -m zensical build``, or pytest).
#: See :func:`_default_workers`; override via ``--package-workers``.
_DEFAULT_PACKAGE_PARALLEL_WORKERS = _DEFAULT_PACKAGE_WORKERS


#: Default slow-test threshold for host CPython tests (seconds).
#: Tests crossing this duration are surfaced as warn-only "SLOW"
#: notices in the rolled-up phase summary — see
#: :func:`_format_pytest_phase_summary`.  Override via
#: ``--slow-test-threshold-cpython``.
_DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON = 1.0


#: Default slow-test threshold for unix-port (MicroPython /
#: CircuitPython compatibility) tests (seconds).  Higher than CPython
#: because each unix-port test pays a subprocess-spawn tax inside the
#: chumicro-pytest-device plugin.  Override via
#: ``--slow-test-threshold-unix-port``.
_DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT = 2.0


#: Env var the parent dispatcher sets when re-invoking ``scripts/run.py``
#: as a subprocess.  The child treats its presence as "I'm being driven
#: by a parent dispatcher; print raw lines, the parent will re-frame
#: them under the right phase header."  Without this signal the child
#: would build its own dispatcher and the parent would see nested
#: ``[label] [inner-label] line`` framing.
_RAW_OUTPUT_ENV_VAR = "CHUMICRO_RAW_OUTPUT"

#: Explicit user override for the output mode.  When set, takes
#: precedence over TTY / IDE auto-detection (but not over
#: ``CHUMICRO_RAW_OUTPUT`` — that's an internal subprocess signal).
#: Useful in IDE Run-config environments where ``isatty()`` is False
#: but the user is reading the output live in an interactive console.
#: Accepted values: ``status``, ``interleave``, ``quiet``.
_OUTPUT_MODE_ENV_VAR = "CHUMICRO_OUTPUT_MODE"


# ---------------------------------------------------------------------------
# Output dispatcher: routes parallel-phase output to the user.
#
# Three modes:
#
# - ``quiet``: every line is buffered; on finish() the dispatcher
#   replays each phase's full transcript under a ``== <label> ==``
#   header in submission order.  This is the original (pre-2026-05)
#   behavior and the default for ``--quiet`` / agent / log-capture
#   contexts.
# - ``interleave``: phase events (started / done) and every line of
#   output print live, prefixed with ``[label]``.  Default for
#   non-TTY contexts (CI logs, ``run.py preflight > out.log``).
# - ``status``: phase events print live (``→ lint``, ``✓ lint
#   (1.2s)``); per-line output is suppressed during the run; on
#   finish(), failed phases get a full transcript dump under a
#   ``== <label> (failed) ==`` header.  Default for TTY contexts.
# - ``raw``: a fourth mode used only by the child of a subprocess
#   re-invocation (when ``CHUMICRO_RAW_OUTPUT`` is set in the env).
#   Lines print raw to stdout so the parent's pipe reader can frame
#   them.  No phase events, no headers.
#
# The dispatcher is constructed by :func:`_pick_dispatcher` based on
# CLI flag + TTY + env-var detection.
# ---------------------------------------------------------------------------


class _Sink:
    """Per-phase output sink — passed into a phase callable.

    Each phase callable receives a sink and emits lines through it via
    ``sink.line(text)``.  The sink records every line into a local
    buffer (so ``sink.captured`` returns the full transcript at the
    end) *and* forwards it to the dispatcher for live routing.

    The streaming subprocess helper :func:`shared.stream_subprocess`
    accepts ``on_line=sink.line`` so phase callables can pipe child
    output through the sink with one line of glue.
    """

    __slots__ = ("_dispatcher", "_label", "_buffer")

    def __init__(self, dispatcher: _Dispatcher, label: str) -> None:
        self._dispatcher = dispatcher
        self._label = label
        self._buffer: list[str] = []

    def line(self, text: str) -> None:
        """Record one line and forward it to the dispatcher."""
        self._buffer.append(text)
        self._dispatcher.phase_line(self._label, text)

    @property
    def captured(self) -> str:
        """Return the full captured transcript with a trailing newline."""
        if not self._buffer:
            return ""
        return "\n".join(self._buffer) + "\n"


class _Dispatcher:
    """Coordinates output from multiple parallel phases.

    Lifecycle: ``start(labels)`` → many ``phase_started`` /
    ``phase_line`` / ``phase_done`` calls (concurrent, from worker
    threads) → ``finish()``.  Implementations must serialize their own
    output (e.g. with a lock) — phase callbacks fire from worker
    threads.
    """

    def start(self, labels: list[str]) -> None:
        """Called once before any phase runs.  *labels* is submission order."""

    def phase_started(self, label: str) -> None:
        """Called when a phase begins running."""

    def phase_line(self, label: str, text: str) -> None:
        """Called for every line of output the phase emits."""

    def phase_done(self, label: str, exit_code: int, captured: str) -> None:
        """Called when a phase finishes.  *captured* is the full transcript."""

    def finish(self) -> None:
        """Called once after all phases complete.  Render finals."""

    def captured_outputs(self) -> dict[str, str]:
        """Return per-phase captured output keyed by label.

        Empty for dispatchers that don't buffer (the live ``Interleave``
        mode prints every line and keeps nothing).  Used by preflight
        to aggregate pytest result counts across phases for the
        end-of-run summary.
        """
        return {}


class _QuietDispatcher(_Dispatcher):
    """Buffer everything, replay at finish() in submission order.

    The original (pre-2026-05) behavior preserved as a fallback for
    ``--quiet``, agent / log-capture contexts, and any consumer that
    wants the deterministic per-phase header layout.
    """

    def __init__(self) -> None:
        self._labels: list[str] = []
        self._results: dict[str, tuple[int, str]] = {}

    def start(self, labels: list[str]) -> None:
        self._labels = list(labels)

    def phase_done(self, label: str, exit_code: int, captured: str) -> None:
        self._results[label] = (exit_code, captured)

    def captured_outputs(self) -> dict[str, str]:
        return {label: captured for label, (_, captured) in self._results.items()}

    def finish(self) -> None:
        has_failure = any(
            self._results.get(label, (0, ""))[0] != 0
            for label in self._labels
        )
        first_failure: str | None = None
        for label in self._labels:
            exit_code, captured = self._results.get(label, (0, ""))
            # When any phase failed, suppress passing-phase transcripts —
            # otherwise the user has to scroll past N successful phases
            # to find the actual error.  Header-only line keeps the
            # phase visible in the log without burying the failure.
            if has_failure and exit_code == 0:
                print(f"== {label} (passed) ==")
                continue
            marker = " (failed)" if exit_code != 0 else ""
            print(f"== {label}{marker} ==")
            if captured:
                print(captured, end="" if captured.endswith("\n") else "\n")
            if exit_code != 0 and first_failure is None:
                first_failure = label
                print(f"Step failed: {label}")


class _InterleaveDispatcher(_Dispatcher):
    """Live phase events + ``[label]``-prefixed lines.

    Default for non-TTY contexts (CI, redirected stdout).  Lines from
    different phases interleave but each is prefixed with its phase
    label so log readers can grep / filter by phase.
    """

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()

    def start(self, labels: list[str]) -> None:
        with self._lock:
            print(f"Running {len(labels)} phase(s) in parallel...", flush=True)

    def phase_started(self, label: str) -> None:
        with self._lock:
            print(f"  -> {label}", flush=True)

    def phase_line(self, label: str, text: str) -> None:
        with self._lock:
            print(f"[{label}] {text}", flush=True)

    def phase_done(self, label: str, exit_code: int, captured: str) -> None:
        marker = "OK" if exit_code == 0 else "FAIL"
        with self._lock:
            print(f"  [{marker}] {label} (exit={exit_code})", flush=True)


class _StatusDispatcher(_Dispatcher):
    """Live phase events with elapsed time; failure logs dumped at end.

    Default for TTY contexts.  Suppresses per-line output while phases
    run (just shows ``->`` / ``OK`` / ``FAIL`` events), then dumps the
    full transcript of any failed phase at finish() time so a developer
    sees what broke without ten phases of noise scrolling by.
    """

    def __init__(self) -> None:
        import threading
        import time
        self._lock = threading.Lock()
        self._time = time
        self._labels: list[str] = []
        self._started: dict[str, float] = {}
        self._results: dict[str, tuple[int, str]] = {}

    def start(self, labels: list[str]) -> None:
        self._labels = list(labels)
        with self._lock:
            print(f"Running {len(labels)} phase(s) in parallel...", flush=True)

    def phase_started(self, label: str) -> None:
        with self._lock:
            self._started[label] = self._time.monotonic()
            print(f"  -> {label}", flush=True)

    def phase_done(self, label: str, exit_code: int, captured: str) -> None:
        end = self._time.monotonic()
        elapsed = end - self._started.get(label, end)
        with self._lock:
            self._results[label] = (exit_code, captured)
            marker = "OK  " if exit_code == 0 else "FAIL"
            print(f"  [{marker}] {label} ({elapsed:.1f}s)", flush=True)

    def captured_outputs(self) -> dict[str, str]:
        return {label: captured for label, (_, captured) in self._results.items()}

    def finish(self) -> None:
        first_failure: str | None = None
        for label in self._labels:
            exit_code, captured = self._results.get(label, (0, ""))
            if exit_code == 0:
                continue
            if first_failure is None:
                first_failure = label
            print(f"\n== {label} (failed) ==")
            if captured:
                print(captured, end="" if captured.endswith("\n") else "\n")
        if first_failure is not None:
            print(f"\nStep failed: {first_failure}")


class _RawDispatcher(_Dispatcher):
    """Used inside a child of a subprocess re-invocation.

    The parent ran us via ``Popen`` with ``CHUMICRO_RAW_OUTPUT=1`` set
    in the env.  We're one phase of the parent's run; the parent will
    read our stdout line-by-line and re-frame each line under the right
    phase header.  Emit raw lines, no phase events.
    """

    def phase_line(self, label: str, text: str) -> None:
        print(text, flush=True)


_DISPATCHERS_BY_NAME: dict[str, type[_Dispatcher]] = {
    "status": _StatusDispatcher,
    "interleave": _InterleaveDispatcher,
    "quiet": _QuietDispatcher,
}


def _is_interactive_console() -> bool:
    """Return True if a human is reading the output in an interactive console.

    `sys.stdout.isatty()` is the obvious signal, but IDEs (PyCharm,
    IntelliJ) capture stdout through a pipe to render it in their own
    Run console pane — `isatty()` returns False even though the user is
    watching live.  Detect those by env var so the IDE Run button shows
    the same status output the user gets in a real terminal.
    """
    if sys.stdout.isatty():
        return True
    # PyCharm / IntelliJ Run configurations.  Set by the IDE in every
    # script's environment, including for ``Preflight`` (Ctrl+Shift+B).
    if os.environ.get("PYCHARM_HOSTED"):
        return True
    return False


def _pick_dispatcher(*, quiet: bool) -> _Dispatcher:
    """Construct the right dispatcher for this invocation context.

    Resolution order:
      1. ``CHUMICRO_RAW_OUTPUT`` env var → raw (we're a child of a
         parent dispatcher; never user-set).
      2. ``--quiet`` flag → quiet.
      3. ``CHUMICRO_OUTPUT_MODE`` env var → the named dispatcher.
         Lets IDEs and CI configs pin a mode without changing the
         CLI invocation.
      4. interactive console (TTY or PyCharm Run pane) → status.
      5. otherwise → interleave (non-interactive CI / log capture).
    """
    if os.environ.get(_RAW_OUTPUT_ENV_VAR):
        return _RawDispatcher()
    if quiet:
        return _QuietDispatcher()
    explicit = os.environ.get(_OUTPUT_MODE_ENV_VAR, "").lower()
    if explicit in _DISPATCHERS_BY_NAME:
        return _DISPATCHERS_BY_NAME[explicit]()
    if _is_interactive_console():
        return _StatusDispatcher()
    return _InterleaveDispatcher()


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def setup() -> int:
    """Install development dependencies, libraries, and IDE configuration.

    Thin CLI wrapper around :func:`shared.install_workspace`, which is the
    single source of truth shared with ``scripts/prepare_workspace.py``.
    See [Decision 0012](../plans/decisions/0012-ide-type-stubs.md) for the
    runtime-pinned type-stub policy.
    """
    from shared import install_workspace
    return install_workspace()


def sync_ide() -> int:
    """Regenerate IDE configuration files (no-op for the workspace itself)."""
    from ide_sync import sync_ide as _sync_ide
    return _sync_ide()


def prepare_micropython() -> int:
    """Build the MicroPython unix-port binary."""
    from prepare_micropython import prepare_micropython as _prepare
    return _prepare()


def prepare_circuitpython() -> int:
    """Build the CircuitPython unix-port binary."""
    from prepare_circuitpython import prepare_circuitpython as _prepare
    return _prepare()


def prepare_mpy_cross() -> int:
    """Build mpy-cross compilers for both runtimes."""
    from prepare_mpy_cross import prepare_mpy_cross as _prepare
    return _prepare()


def verify_examples(package_dirs: list[Path]) -> int:
    """Verify examples have valid syntax and resolvable imports."""
    from verify_examples import verify_examples as _verify
    return _verify(package_dirs)


def new_library(name: str) -> int:
    """Scaffold a new device library."""
    from new_library_scaffold import new_library as _new_library
    return _new_library(name)


def docs_deploy(channel: str, libraries: list[str] | None = None) -> int:
    """Deploy versioned docs for the selected libraries."""
    from docs_deploy import docs_deploy as _docs_deploy
    return _docs_deploy(channel, libraries=libraries)


def lint() -> int:
    """Run Ruff plus the chumicro-specific CHU lint checks.

    Every CHU rule lives in the `chumicro-checks` package; this
    function shells out to its CLI after ruff finishes.
    """
    ruff_result = run_command([PYTHON, "-m", "ruff", "check", *discover_ruff_paths()])
    if ruff_result != 0:
        return ruff_result
    return run_command([PYTHON, "-m", "chumicro_checks"])


def _parse_library_filters(
    filter_expression: str,
) -> dict[str, list[tuple[str | None, str]]]:
    """Parse a ``-k`` expression into per-library test filters.

    Every entry must be library-scoped.  Supported formats::

        library/expression              filter by name within a library
        library/file/expression         filter within a specific test file
        lib1/a,lib2/b                   comma-separated entries

    Returns ``{library_name: [(file_or_None, expression), ...]}``.
    Multiple unscoped entries for the same library are combined with
    ``or`` at run time.  File-scoped entries each get their own pytest
    invocation.

    Raises :class:`SystemExit` for entries missing a library prefix.
    """
    entries = [entry.strip() for entry in filter_expression.split(",") if entry.strip()]
    result: dict[str, list[tuple[str | None, str]]] = {}

    for entry in entries:
        parts = entry.split("/")
        if len(parts) == 2:
            library_name, expression = parts
            result.setdefault(library_name, []).append((None, expression))
        elif len(parts) == 3:
            library_name, file_name, expression = parts
            result.setdefault(library_name, []).append((file_name, expression))
        else:
            print(f"Invalid -k format: {entry}")
            print(
                "Use library/test, library/file/test, "
                "or comma-separated entries."
            )
            raise SystemExit(1)

    return result


def _resolve_filter_and_scope(
    filter_expression: str | None,
    package_dirs: list[Path],
) -> tuple[list[Path], dict[str, list[tuple[str | None, str]]] | None] | None:
    """Narrow ``package_dirs`` and build the per-library filter plan.

    Handles both filter forms:

    - **Bare** (``heartbeat``) — standard pytest ``-k``.  ``package_dirs``
      is untouched; every selected library runs with this expression.
    - **Library-scoped** (``timing/test_heartbeat``) — the named
      libraries replace whatever scope was selected by ``--all`` /
      ``--libraries`` / change detection.

    Args:
        filter_expression: Raw ``-k`` argument, or ``None``.
        package_dirs: Initial scope from the CLI.

    Returns:
        ``(package_dirs, per_library)`` on success, or ``None`` when an
        unknown library was named in a library-scoped filter (the
        caller should return exit code 1; the error message has
        already been printed).
    """
    if not filter_expression:
        return package_dirs, None

    entries = [entry.strip() for entry in filter_expression.split(",") if entry.strip()]
    if entries and all("/" not in entry for entry in entries):
        # Bare pytest-style filter — leave package_dirs alone.
        return package_dirs, {
            package_dir.name: [(None, filter_expression)]
            for package_dir in package_dirs
        }

    # Library-scoped — library names override package_dirs.
    parsed = _parse_library_filters(filter_expression)
    by_name = {package_dir.name: package_dir for package_dir in discover_package_dirs()}
    resolved: list[Path] = []
    for name in parsed:
        if name not in by_name:
            available = ", ".join(sorted(by_name))
            print(f"Unknown library in -k: {name}")
            print(f"Available: {available}")
            return None
        resolved.append(by_name[name])
    return resolved, parsed


def _coverage_gate_args(
    package_name: str,
    *,
    skip_coverage_gate: bool,
    coverage_threshold: int | None,
    elevated_packages: set[str] | None,
) -> list[str]:
    """Return the pytest ``--cov-fail-under`` args for one library.

    When ``elevated_packages`` is set, only those libraries get the
    overridden threshold; the rest fall back to the ``pyproject.toml``
    default (no ``--cov-fail-under`` flag added).
    """
    if skip_coverage_gate:
        return ["--cov-fail-under=0"]
    if coverage_threshold is None:
        return []
    if elevated_packages is None or package_name in elevated_packages:
        return [f"--cov-fail-under={coverage_threshold}"]
    return []


def _plan_test_runs_for_library(
    package_dir: Path,
    per_library: dict[str, list[tuple[str | None, str]]] | None,
) -> list[tuple[str, str]] | None:
    """Build the ordered list of pytest invocations for one library.

    Filter entries split into two categories:

    - **Global** (no file specified) — combined with ``or`` into a single
      pytest invocation across the whole ``tests/`` directory.
    - **File-scoped** (``library/file/expression``) — each gets its own
      pytest invocation targeting a specific test file so coverage data
      stays attributable.

    Args:
        package_dir: The library's root directory.
        per_library: Parsed filter plan keyed by library name, or
            ``None`` to run the entire ``tests/`` directory.

    Returns:
        List of ``(test_target, expression)`` tuples, or ``None`` when
        a file-scoped entry names a test file that doesn't exist (the
        caller should return exit code 1; the error message has
        already been printed).
    """
    test_path = str((package_dir / "tests").relative_to(ROOT))

    if per_library is None:
        return [(test_path, "")]

    entries = per_library.get(package_dir.name, [])
    global_expressions = [
        expression for file_name, expression in entries if file_name is None
    ]
    file_entries = [
        (file_name, expression) for file_name, expression in entries
        if file_name is not None
    ]

    runs: list[tuple[str, str]] = []
    if global_expressions:
        runs.append((test_path, " or ".join(global_expressions)))

    for file_name, expression in file_entries:
        test_file = package_dir / "tests" / f"{file_name}.py"
        if not test_file.exists():
            print(f"Test file not found: {test_file.relative_to(ROOT)}")
            return None
        runs.append((str(test_file.relative_to(ROOT)), expression))

    return runs


def _combine_and_report_coverage(
    *,
    skip_coverage_gate: bool,
    coverage_threshold: int | None,
    elevated_packages: set[str] | None,
    overall_exit_code: int,
) -> int:
    """Combine per-run coverage files, report, and return the final exit code.

    The per-library ``--cov-fail-under`` gates enforced inside the main
    loop are the primary mechanism.  The combined report additionally
    applies the override when every library was held to the same
    threshold (no ``elevated_packages`` scoping) — when it *is* scoped,
    the combined report uses the ``pyproject.toml`` default because
    the unchanged libraries shouldn't be held to the higher bar.
    """
    if not list(ROOT.glob(".coverage.*")):
        return overall_exit_code

    run_command([PYTHON, "-m", "coverage", "combine"])

    report_args = [PYTHON, "-m", "coverage", "report", "--show-missing"]
    if skip_coverage_gate:
        report_args.append("--fail-under=0")
    elif coverage_threshold is not None and elevated_packages is None:
        report_args.append(f"--fail-under={coverage_threshold}")

    report_exit_code = run_command(report_args)
    if report_exit_code == 0 or overall_exit_code != 0:
        return overall_exit_code

    if not skip_coverage_gate:
        print(
            "\nHint: check the Missing column above to find uncovered"
            " lines.  If the gap is in code you didn't change, note it"
            " in your PR — a maintainer can help."
        )
    return report_exit_code


def test_cpython(
    package_dirs: list[Path],
    *,
    filter_expression: str | None = None,
    exit_first: bool = False,
    verbose: bool = False,
    no_cov: bool = False,
    coverage_threshold: int | None = None,
    elevated_packages: set[str] | None = None,
    package_workers: int = _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    quiet: bool = False,
    slow_test_threshold_s: float = _DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
) -> int:
    """Run the CPython test suite for the given packages.

    Runs pytest separately for each package to avoid test-directory name
    collisions (Decision 0009), then combines and reports coverage.  Each
    library must independently meet the coverage threshold unless
    *filter_expression* is set (filtering naturally reduces coverage) or *no_cov*
    skips coverage entirely.

    The default threshold comes from ``pyproject.toml`` (85 % — the human
    baseline).  Pass *coverage_threshold* to override it; agents use 94 %
    (Decision 0025).

    When *elevated_packages* is provided, only those libraries (by name)
    use *coverage_threshold*; all other libraries fall back to the
    ``pyproject.toml`` default.  This lets agents enforce a higher bar on
    the libraries they changed without failing on pre-existing coverage
    in libraries they didn't touch.

    *filter_expression* accepts two forms::

        heartbeat                             # bare pytest -k — applied to all selected libraries
        timing/test_heartbeat                 # library-scoped: by name in one library
        timing/test_ticks/ticks_add           # library-scoped: by file and name
        timing/ticks_diff,runner/task_handle  # comma-separated library-scoped entries

    Bare filters (no ``/``) match vanilla pytest's ``-k`` semantics and
    preserve whatever scope was already selected (``--all``,
    ``--libraries``, or change detection).  Library-scoped filters
    override the scope and target only the named libraries.
    """
    resolved = _resolve_filter_and_scope(filter_expression, package_dirs)
    if resolved is None:
        return 1
    package_dirs, per_library = resolved

    testable = [package_dir for package_dir in package_dirs if (package_dir / "tests").is_dir()]
    if not testable:
        print("No test directories found for the selected packages.")
        return 0

    environment = pythonpath_environment()

    # Clean stale coverage data so combine starts fresh.  Two globs are
    # needed: `.coverage` (the default combined file) and `.coverage.*`
    # (the per-run files we create below with unique suffixes).
    for coverage_file in ROOT.glob(".coverage"):
        coverage_file.unlink()
    for coverage_file in ROOT.glob(".coverage.*"):
        coverage_file.unlink()

    # Skip coverage enforcement when either:
    #   - filter_expression is set (selecting a subset of tests naturally
    #     reduces branch coverage below the configured threshold), or
    #   - no_cov is set (user explicitly opted out of coverage).
    skip_coverage_gate = bool(filter_expression) or no_cov

    # Build one phase per (library, test-target) pair so the fan-out
    # below stays at the granularity Decision 0009 requires (per-
    # library pytest invocation, distinct ``COVERAGE_FILE`` per run).
    # Each phase streams its stdout/stderr through the dispatcher,
    # which routes the lines to the right place (live status, prefixed
    # interleave, or buffered replay) based on TTY + ``--quiet``.
    phases: list[tuple[str, Callable[[_Sink], int]]] = []
    collector = _PytestResultCollector()
    durations_args = [
        "--durations=0", f"--durations-min={slow_test_threshold_s}",
    ]
    run_counter = 0
    for package_dir in testable:
        runs = _plan_test_runs_for_library(package_dir, per_library)
        if runs is None:
            return 1

        cov_gate_args = _coverage_gate_args(
            package_dir.name,
            skip_coverage_gate=skip_coverage_gate,
            coverage_threshold=coverage_threshold,
            elevated_packages=elevated_packages,
        )

        for test_target, expression in runs:
            extra_args: list[str] = []
            if expression:
                extra_args.extend(["-k", expression])
            if exit_first:
                extra_args.append("-x")
            if verbose:
                extra_args.append("-v")

            cov_args = [] if no_cov else coverage_args_for([package_dir])

            # Disable the auto-registered chumicro-pytest-device plugin
            # for unit-test runs.  The plugin only intercepts paths
            # under ``functional_tests/``, so it adds nothing for the
            # ``tests/`` sweep here.  But its ``pytest11`` entry point
            # would otherwise import the plugin's modules (which pull
            # in ``chumicro_deploy``) at session start — *before*
            # pytest-cov begins instrumenting, missing import-time
            # coverage (dataclass definitions, regex compiles) on
            # both the plugin's tree and ``chumicro_deploy.config.default``.
            # Functional-test runs (``test-libraries-functional``) load
            # the plugin via the same entry point and aren't affected
            # because they don't measure coverage of those modules.
            disable_plugin_args = ["-p", "no:chumicro_pytest_device"]

            # Unique coverage file per run keeps data attributable
            # under parallel fan-out — every concurrent pytest writes
            # to its own ``.coverage.<package>.<run>`` file before
            # ``coverage combine`` merges them.
            coverage_name = f".coverage.{package_dir.name}.{run_counter}"
            run_counter += 1
            command = [
                PYTHON, "-m", "pytest",
                "-W", "error",
                *cov_args,
                "--cov-report=",
                *cov_gate_args,
                *durations_args,
                *disable_plugin_args,
                test_target,
                *extra_args,
            ]
            run_environment = {
                **environment, "COVERAGE_FILE": str(ROOT / coverage_name),
            }
            label = f"{package_dir.relative_to(ROOT)}/{Path(test_target).name}"
            phases.append(
                (
                    label,
                    _make_pytest_phase(
                        command, run_environment,
                        result_collector=collector,
                        label=label,
                    ),
                ),
            )

    overall_exit_code, _failing_label = _run_parallel_phases(
        phases,
        dispatcher=_pick_dispatcher(quiet=quiet),
        max_workers=package_workers,
    )

    for line in _format_pytest_phase_summary(
        "test",
        collector.results,
        slow_threshold_s=slow_test_threshold_s,
    ):
        print(line)

    if no_cov:
        return overall_exit_code
    return _combine_and_report_coverage(
        skip_coverage_gate=skip_coverage_gate,
        coverage_threshold=coverage_threshold,
        elevated_packages=elevated_packages,
        overall_exit_code=overall_exit_code,
    )


def _run_pytest_capturing(
    command: list[str], environment: dict[str, str], sink: _Sink,
) -> int:
    """Run a pytest invocation streaming output line-by-line through *sink*.

    Single seam :func:`_make_pytest_phase` calls and tests monkey-
    patch.  Streams output via :func:`shared.stream_subprocess` so the
    parallel test_cpython fan-out delivers lines to the dispatcher as
    they arrive (rather than buffering until the subprocess exits).

    Pytest exit code 5 ("no tests collected" — typically when a
    ``-k`` filter matches nothing in a given library) is normalized
    to 0 so it doesn't fail the whole sweep.  The "no tests ran" line
    still flows through the sink for log visibility.
    """
    sink.line(f"+ {' '.join(command)}")
    exit_code, _ = stream_subprocess(
        command,
        cwd=ROOT,
        environment=environment,
        on_line=sink.line,
    )
    return 0 if exit_code == 5 else exit_code


def _make_pytest_phase(
    command: list[str], environment: dict[str, str],
    *,
    result_collector: _PytestResultCollector | None = None,
    label: str | None = None,
) -> Callable[[_Sink], int]:
    """Wrap a pytest invocation as a streaming phase callable.

    The returned closure is what :func:`_run_parallel_phases`
    schedules per package.  Delegates to :func:`_run_pytest_capturing`
    so tests can monkeypatch one well-known seam to observe the
    constructed pytest command line.

    When *result_collector* is provided, the phase additionally parses
    the pytest output for the ``=== N passed in Xs ===`` summary line
    plus the ``slowest durations`` block, suppresses those lines from
    the sink, and stores a :class:`_PytestRunResult` under *label* so
    the parent fan-out can emit a rolled-up phase summary.
    """
    if result_collector is None:
        return lambda sink: _run_pytest_capturing(command, environment, sink)

    phase_label = label or " ".join(command)

    def phase(sink: _Sink) -> int:
        filter_state = _PytestOutputFilter()
        wrapped = _FilteringSink(sink, filter_state)
        exit_code = _run_pytest_capturing(command, environment, wrapped)
        result_collector.record(
            _PytestRunResult.build(phase_label, exit_code, filter_state),
        )
        return exit_code

    return phase


# ---------------------------------------------------------------------------
# Pytest output parsing: filter per-library summary lines into a
# per-fan-out aggregate so the user sees one rolled-up "N passed across
# M libraries in Xs" line instead of N noisy per-library summaries.
# Also collects "slowest durations" entries so the parent phase can
# surface a warn-only "SLOW (>Xs)" notice.
# ---------------------------------------------------------------------------


_PYTEST_SLOW_HEADER = re.compile(r"^=+\s*slowest durations\s*=+\s*$")
_PYTEST_SLOW_ROW = re.compile(
    r"^(?P<duration>\d+\.\d+)s\s+(?P<phase>call|setup|teardown)\s+(?P<test_id>\S+)\s*$",
)
_PYTEST_SLOW_TRAILER = re.compile(r"^\(\d+ durations? < .* hidden\.\)\s*$")
_PYTEST_RESULT_FULL = re.compile(
    r"^=+\s*"
    r"(?:(?P<passed>\d+)\s+passed)?"
    r"(?:,\s+(?P<skipped>\d+)\s+skipped)?"
    r"(?:,\s+(?P<deselected>\d+)\s+deselected)?"
    r"(?:,\s+\d+\s+warnings?)?"
    r"\s+in\s+(?P<duration>\d+\.\d+)s",
)
_PYTEST_NO_TESTS_RAN = re.compile(r"^=+\s*no tests ran\s+in\s+\d+\.\d+s")


@dataclass
class _PytestRunResult:
    """Parsed summary of a single pytest invocation."""

    label: str
    exit_code: int
    passed: int = 0
    skipped: int = 0
    duration_s: float = 0.0
    slow_tests: list[tuple[float, str]] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        label: str,
        exit_code: int,
        filter_state: _PytestOutputFilter,
    ) -> _PytestRunResult:
        return cls(
            label=label,
            exit_code=exit_code,
            passed=filter_state.passed,
            skipped=filter_state.skipped,
            duration_s=filter_state.duration_s,
            slow_tests=list(filter_state.slow_tests),
        )


class _PytestResultCollector:
    """Thread-safe accumulator for :class:`_PytestRunResult` objects.

    Phase closures (run from worker threads via
    :func:`_run_parallel_phases`) call :meth:`record` to deposit one
    result per pytest invocation.  The parent fan-out reads
    :attr:`results` after the parallel block completes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._results: list[_PytestRunResult] = []

    def record(self, result: _PytestRunResult) -> None:
        with self._lock:
            self._results.append(result)

    @property
    def results(self) -> list[_PytestRunResult]:
        with self._lock:
            return list(self._results)


class _PytestOutputFilter:
    """State machine that intercepts pytest summary + durations lines.

    Plugged into a :class:`_FilteringSink`, this consumes the noisy
    per-library summary lines (``=== N passed in Xs ===``) and the
    ``slowest durations`` block, parsing them into structured fields
    that the parent fan-out reads via :meth:`_PytestRunResult.build`.
    Returns ``True`` from :meth:`consume` when a line was absorbed —
    the wrapping sink then suppresses forwarding to the dispatcher.

    Lines that don't match a known summary form (test progress dots,
    failure tracebacks, "+ pytest ..." command echo, etc.) pass
    through unchanged.
    """

    def __init__(self) -> None:
        self.passed = 0
        self.skipped = 0
        self.duration_s = 0.0
        self.slow_tests: list[tuple[float, str]] = []
        self._in_slow_block = False

    def consume(self, text: str) -> bool:
        stripped = text.rstrip()
        if _PYTEST_SLOW_HEADER.match(stripped):
            self._in_slow_block = True
            return True
        if self._in_slow_block:
            row = _PYTEST_SLOW_ROW.match(stripped)
            if row is not None:
                # Only count ``call`` durations — setup / teardown
                # often dominate fast tests via fixture cost but
                # aren't what the user means by "this test is slow".
                if row.group("phase") == "call":
                    self.slow_tests.append(
                        (float(row.group("duration")), row.group("test_id")),
                    )
                return True
            if _PYTEST_SLOW_TRAILER.match(stripped):
                return True
            if not stripped:
                return True
            # Anything else ends the block (the final ``=== N passed ===``
            # line falls through to the summary handler below).
            self._in_slow_block = False
        match = _PYTEST_RESULT_FULL.match(stripped)
        if match is not None:
            if match.group("passed"):
                self.passed += int(match.group("passed"))
            if match.group("skipped"):
                self.skipped += int(match.group("skipped"))
            self.duration_s += float(match.group("duration"))
            return True
        if _PYTEST_NO_TESTS_RAN.match(stripped):
            return True
        return False


class _FilteringSink:
    """Duck-typed sink wrapper that routes through a :class:`_PytestOutputFilter`.

    Lines the filter consumes are dropped before reaching the inner
    sink (and therefore the dispatcher).  Everything else flows through
    unchanged so progress dots and failure tracebacks still surface.
    """

    __slots__ = ("_inner", "_filter")

    def __init__(self, inner: _Sink, filter_state: _PytestOutputFilter) -> None:
        self._inner = inner
        self._filter = filter_state

    def line(self, text: str) -> None:
        if self._filter.consume(text):
            return
        self._inner.line(text)

    @property
    def captured(self) -> str:
        return self._inner.captured


def _format_pytest_phase_summary(
    label: str,
    results: Sequence[_PytestRunResult],
    *,
    slow_threshold_s: float,
) -> list[str]:
    """Build the rolled-up summary lines for a pytest phase.

    Returns one summary line plus optional SLOW notices.  The summary
    follows pytest's own ``X passed [, Y skipped] in Zs`` shape so log
    scanners that already grep for "passed in" keep working, prefixed
    with the phase label.  When *results* spans multiple pytest
    invocations (per-package fan-out under :func:`test_cpython`) the
    line gains an ``across N libraries`` clause; a single invocation
    omits it.

    Slow notices list every test whose ``call`` duration crossed
    *slow_threshold_s*.  Warn-only — the caller's exit code is
    unaffected.
    """
    passed = sum(result.passed for result in results)
    skipped = sum(result.skipped for result in results)
    duration_s = sum(result.duration_s for result in results)

    pieces = [f"{passed} passed"]
    if skipped:
        pieces.append(f"{skipped} skipped")
    summary = f"{label}: {', '.join(pieces)}"
    if len(results) > 1:
        summary += f" across {len(results)} libraries"
    summary += f" in {duration_s:.2f}s"
    lines = [summary]
    slow_entries: list[tuple[float, str]] = []
    for result in results:
        for duration, test_id in result.slow_tests:
            if duration >= slow_threshold_s:
                slow_entries.append((duration, test_id))
    if slow_entries:
        slow_entries.sort(reverse=True)
        lines.append(
            f"{label}: SLOW (>{slow_threshold_s:.1f}s): "
            + ", ".join(
                f"{test_id} ({duration:.2f}s)"
                for duration, test_id in slow_entries
            ),
        )
    return lines


def test_scripts(
    *,
    exit_first: bool = False,
    verbose: bool = False,
) -> int:
    """Run pytest on scripts/tests/ — infrastructure test suite.

    Scripts tests run without a per-library coverage gate since scripts
    are subprocess-heavy orchestration code with a different coverage
    profile than publishable library code.
    """
    test_path = "scripts/tests"
    if not (ROOT / test_path).is_dir():
        print("No scripts/tests/ directory found.")
        return 0

    extra_args: list[str] = []
    if exit_first:
        extra_args.append("-x")
    if verbose:
        extra_args.append("-v")

    return run_command(
        [
            PYTHON, "-m", "pytest",
            "-W", "error",
            test_path,
            *extra_args,
        ],
        environment=pythonpath_environment(),
    )


def _selected_library_dirs(package_dirs: list[Path] | None) -> list[Path]:
    """Return the selected publishable library directories.

    Args:
        package_dirs: Optional scoped package directories from the CLI.
            ``None`` means "all publishable libraries".
    """
    if package_dirs is None:
        return discover_library_dirs()
    libraries_root = ROOT / "libraries"
    return [
        package_dir for package_dir in package_dirs
        if package_dir.parent == libraries_root
    ]


def build(
    *,
    package_workers: int = _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    quiet: bool = False,
) -> int:
    """Build all publishable package distributions.

    Uses ``--no-isolation`` to skip creating fresh virtual environments
    for each build, which dramatically speeds up builds (~10x faster).
    This is safe because the development environment already has
    ``hatchling`` installed via ``requirements-dev.txt``.

    Builds are fanned out across *package_workers* threads — each
    ``python -m build`` is an independent subprocess with its own
    per-package ``dist/`` output, no shared state.
    """
    packages = find_publishable_packages()
    if not packages:
        print("No publishable packages found (no VERSION + pyproject.toml pairs).")
        return 1

    def build_one(package: str) -> Callable[[_Sink], int]:
        command = [PYTHON, "-m", "build", "--no-isolation", package]

        def run(sink: _Sink) -> int:
            sink.line(f"+ {' '.join(command)}")
            exit_code, _ = stream_subprocess(command, cwd=ROOT, on_line=sink.line)
            if exit_code != 0:
                sink.line(f"Build failed: {package}")
            return exit_code

        return run

    phases = [(f"build {package}", build_one(package)) for package in packages]
    result, _failing_label = _run_parallel_phases(
        phases,
        dispatcher=_pick_dispatcher(quiet=quiet),
        max_workers=package_workers,
    )
    if result != 0:
        return result

    from sdist_content import check_all_library_sdists

    library_dirs = [
        ROOT / package
        for package in packages
        if package.startswith("libraries/")
    ]
    sdist_problems = check_all_library_sdists(library_dirs)
    if sdist_problems:
        print("Library sdist content check failed:")
        for problem in sdist_problems:
            print(f"  - {problem}")
        return 1

    print(f"Built {len(packages)} package(s): {', '.join(packages)}")
    return 0


def docs(
    package_dirs: list[Path],
    *,
    serve: bool = False,
    package_workers: int = _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    quiet: bool = False,
) -> int:
    """Build docs for selected libraries using Zensical.

    If *serve* is True, starts a live-reload dev server for the first
    selected library instead of building static output.

    The build captures stderr and fails if griffe emits any warnings
    (e.g. missing type annotations or malformed docstrings).  This
    enforces Decision 0021 (type documentation policy).
    """
    # Keep only packages that have a mkdocs.yml
    doc_dirs = discover_doc_dirs(package_dirs)
    if not doc_dirs:
        print("No libraries with mkdocs.yml found for the selected packages.")
        return 0

    from docs_deploy import copy_shared_docs_assets
    copy_shared_docs_assets(doc_dirs)

    if serve:
        # Serve the first selected library
        library_dir = doc_dirs[0]
        relative_path = library_dir.relative_to(ROOT)
        print(f"Serving docs for {relative_path} (Ctrl+C to stop)...")
        return run_command(
            [PYTHON, "-m", "zensical", "serve",
             "-f", str(library_dir / "mkdocs.yml")],
        )

    # Each library's zensical build is an independent subprocess with
    # its own mkdocs.yml + site/ output, so we fan out across
    # *package_workers* to amortize the per-process warm-up.  The
    # serial loop took ~25-30 s on an 18-package workspace; at 4-way
    # fan-out it lands closer to 2-3 s.
    phases: list[tuple[str, Callable[[_Sink], int]]] = [
        (
            f"docs {library_dir.relative_to(ROOT)}",
            _build_one_library_docs_factory(library_dir),
        )
        for library_dir in doc_dirs
    ]
    exit_code, _failing_label = _run_parallel_phases(
        phases,
        dispatcher=_pick_dispatcher(quiet=quiet),
        max_workers=package_workers,
    )
    return exit_code


def _build_one_library_docs_factory(
    library_dir: Path,
) -> Callable[[_Sink], int]:
    """Return a phase callable that runs zensical on *library_dir*.

    The closure streams every line of zensical output through the
    sink, then post-processes the captured transcript to fail on
    griffe warnings (Decision 0021).  Streaming means the dispatcher
    sees output the moment zensical emits it — no buffer-and-replay
    delay even on slow library builds.
    """
    def build_one(sink: _Sink) -> int:
        relative_path = library_dir.relative_to(ROOT)
        site_dir = library_dir / "site"
        # mkdocstrings + griffe cache parsed-AST results in
        # ``<library>/.cache/``.  When cached entries are reused, griffe
        # does not re-emit warnings on stdout — and the warning-scan
        # below would silently pass.  Always wipe the cache so each
        # docs build re-parses every source file from scratch.
        cache_dir = library_dir / ".cache"
        if cache_dir.is_dir():
            for cache_entry in cache_dir.iterdir():
                if cache_entry.name == ".gitignore":
                    continue
                if cache_entry.is_dir():
                    shutil.rmtree(cache_entry)
                else:
                    cache_entry.unlink()
        command = [
            PYTHON, "-m", "zensical", "build",
            "-f", str(library_dir / "mkdocs.yml"),
        ]
        sink.line(f"+ {' '.join(command)}")
        exit_code, captured = stream_subprocess(
            command, cwd=ROOT, on_line=sink.line,
        )
        if exit_code != 0:
            sink.line(f"Docs build failed: {relative_path}")
            return exit_code

        # Fail on griffe warnings (Decision 0021).  Stderr is merged
        # into stdout in the streaming path, so scan the full transcript.
        griffe_warnings = [
            line for line in captured.splitlines()
            if "griffe" in line.lower()
        ]
        if griffe_warnings:
            sink.line(f"Docs build has griffe warnings: {relative_path}")
            for warning in griffe_warnings:
                sink.line(f"  {warning}")
            return 1

        sink.line(f"  Built: {site_dir.relative_to(ROOT)}/")
        return 0

    return build_one


def docs_preview(package_dirs: list[Path]) -> int:
    """Build docs from the current working tree and serve a local preview.

    The preview branch is seeded from ``gh-pages`` (if it exists) so that
    already-deployed stable versions appear alongside the current working
    tree content.  The working tree is then deployed on top as
    ``dev`` / ``experimental``.

    For each library, ``mike deploy`` with ``--deploy-prefix`` mirrors the
    production layout (Decision 0013).  The landing page is injected via a
    git-plumbing commit.  ``mike serve`` then serves the result.
    """
    preview_branch = "_docs-preview"
    source_branch = "gh-pages"

    doc_dirs = discover_doc_dirs(package_dirs)
    if not doc_dirs:
        print("No libraries with mkdocs.yml found for the selected packages.")
        return 0

    from docs_deploy import MIKE, copy_shared_docs_assets, inject_landing_page
    copy_shared_docs_assets(doc_dirs)

    # Delete any previous preview branch so we start fresh.
    subprocess.run(
        ["git", "branch", "-D", preview_branch],
        capture_output=True, cwd=ROOT,
    )

    # Fetch the latest gh-pages from origin so the preview reflects
    # recently promoted versions (CI pushes directly to gh-pages).
    fetch_result = subprocess.run(
        ["git", "fetch", "origin", source_branch],
        capture_output=True, cwd=ROOT,
    )
    if fetch_result.returncode == 0:
        # Fast-forward the local tracking branch to match the remote.
        subprocess.run(
            ["git", "branch", "-f", source_branch, f"origin/{source_branch}"],
            capture_output=True, cwd=ROOT,
        )

    # Seed from gh-pages so existing stable/versioned deploys are present.
    # If gh-pages doesn't exist yet, mike's --allow-empty will create the
    # branch from scratch (first-time setup).
    has_source = subprocess.run(
        ["git", "rev-parse", "--verify", source_branch],
        capture_output=True, cwd=ROOT,
    ).returncode == 0

    if has_source:
        subprocess.run(
            ["git", "branch", preview_branch, source_branch],
            capture_output=True, cwd=ROOT, check=True,
        )
        print(f"Seeded {preview_branch} from {source_branch}.")

    # Per-library deploys are sequential because every ``mike deploy``
    # commits to the same ``_docs-preview`` git branch — running them
    # concurrently would race on the git index lock.  Unlike ``docs``
    # (which fans out per library because each writes to its own
    # ``site/`` directory), the ``mike`` workflow is a serialized git-
    # plumbing pipeline by construction.  Worktree-per-library would
    # let us parallelize, but the wall time of an interactive
    # ``docs-preview`` is dominated by ``mike serve`` afterwards, so
    # the speedup wouldn't be visible to the user.
    for library_dir in doc_dirs:
        relative_path = library_dir.relative_to(ROOT)
        library_name = library_dir.name
        print(f"== deploy {relative_path} ==")
        # --deploy-prefix puts each library's docs in a subdirectory
        # (e.g. /timing/) matching the production gh-pages layout.
        # --allow-empty lets mike create the branch from scratch when
        # gh-pages doesn't exist yet.  "dev" is the version label,
        # "experimental" is the URL alias.
        deploy_args = [
            MIKE, "deploy",
            "--deploy-prefix", library_name,
            "-b", preview_branch,
            "-F", str(library_dir / "mkdocs.yml"),
            "--alias-type", "redirect",
            "--update-aliases",
            "dev", "experimental",
        ]
        # Only needed when gh-pages doesn't exist and the branch is new.
        if not has_source:
            deploy_args.append("--allow-empty")

        exit_code = run_command(deploy_args)
        if exit_code != 0:
            print(f"Docs deploy failed: {relative_path}")
            return exit_code

    inject_landing_page(preview_branch)

    return run_command([
        MIKE, "serve",
        "-b", preview_branch,
        "-F", str(doc_dirs[0] / "mkdocs.yml"),
    ])


def preflight(
    micropython_binary: str | None = None,
    circuitpython_binary: str | None = None,
    coverage_threshold: int | None = None,
    with_functional: bool = False,
    with_device_unit: bool = False,
    phase_workers: int = _DEFAULT_PREFLIGHT_PHASE_PARALLEL_WORKERS,
    package_workers: int = _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    quiet: bool = False,
    slow_test_threshold_cpython: float = _DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
    slow_test_threshold_unix_port: float = _DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
) -> int:
    """Run the full check suite that CI requires on every pull request.

    Mirrors the CI matrix as closely as possible on the local machine:
    lint, build, docs (with griffe warning detection), CPython tests,
    scripts infrastructure tests, example verification, version-check,
    api-check, MicroPython and CircuitPython cross-runtime unit tests.

    The 11 unit-test phases run **in parallel** as independent
    subprocess re-invocations of ``python scripts/run.py <subcommand>``;
    output is captured per phase and replayed in submission order so
    the on-screen log reads as if the loop ran serially.  See
    Decision 0048 for the design.  The ``--with-functional`` tail
    stays serial because both phases drive the same physical hardware.

    Pass *coverage_threshold* to override the ``pyproject.toml`` default
    (85 %).  Agents should pass ``--coverage-threshold 94`` (Decision 0025).

    Tests run once with the current Python interpreter (CI runs 3.11,
    3.12, and 3.13 separately).  Version-check and api-check require
    ``origin/main`` to be reachable; they skip gracefully if it is not.

    Functional tests on real hardware are skipped by default — they
    require a connected board.  Pass *with_functional* to append
    ``test-libraries-functional`` and ``test-workbench-functional``
    (running with ``devices.yml`` defaults) to the end of the sweep.
    Pass *with_device_unit* to also append ``test-unit-on-device``
    (the cross-runtime unit suite on connected boards) after that —
    likewise serial, since it drives the same hardware.
    """
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"

    # When --coverage-threshold is set, only apply the elevated threshold
    # to libraries the caller actually changed.  Libraries the caller
    # didn't touch keep the pyproject.toml default (85 %).  This prevents
    # agents from failing on pre-existing coverage in human-authored code.
    elevated_package_names: list[str] | None = None
    if coverage_threshold is not None:
        changed = detect_changed_packages()
        if changed is not None:
            elevated_package_names = sorted(
                package_dir.name for package_dir in changed
            )
        # When changed is None (infrastructure change or no diff), all
        # packages are considered "changed" — leave elevated_package_names
        # as None so the threshold applies everywhere.

    # version-check and api-check need a base ref to diff against.
    # If origin/main isn't reachable (detached HEAD, no remote, etc.),
    # skip them with a warning rather than crashing preflight.  We
    # decide reachability here in the parent so the parallel block
    # never sees an unreachable phase — the skip line prints in the
    # per-phase ordering below.
    base_reference = "origin/main"
    can_diff = is_ref_reachable(base_reference)

    # Build the parallel-phase list.  Order matters for log replay:
    # `_run_capture_phases_in_parallel` prints headers + captured
    # output in submission order, so the log keeps the documented
    # "lint first, test-circuitpython last" shape regardless of
    # which phase actually finishes first.
    # Forward --package-workers to subcommands whose internal fan-out
    # honors the cap (test, build, docs, check-api).  Phases that don't
    # fan out per-package (lint, test-scripts, verify-examples,
    # check-dep-graph, check-version, test-micropython,
    # test-circuitpython) ignore it.
    package_workers_args = ["--package-workers", str(package_workers)]
    check_api_workers_args = ["--max-workers", str(package_workers)]

    test_args = [
        "test", "--all", *package_workers_args,
        "--slow-test-threshold-cpython", str(slow_test_threshold_cpython),
    ]
    if coverage_threshold is not None:
        test_args.extend(["--coverage-threshold", str(coverage_threshold)])
    if elevated_package_names is not None:
        test_args.extend(
            ["--elevated-packages", ",".join(elevated_package_names)],
        )

    unix_port_shared_args = [
        "--slow-test-threshold-unix-port", str(slow_test_threshold_unix_port),
    ]

    test_micropython_args = ["test-micropython", *unix_port_shared_args]
    if micropython_binary is not None:
        test_micropython_args.extend(["--micropython-binary", micropython_binary])

    test_circuitpython_args = ["test-circuitpython", *unix_port_shared_args]
    if circuitpython_binary is not None:
        test_circuitpython_args.extend(
            ["--circuitpython-binary", circuitpython_binary],
        )

    parallel_specs: list[tuple[str, list[str] | None]] = [
        ("lint", ["lint"]),
        ("build", ["build", *package_workers_args]),
        ("docs", ["docs", "--all", *package_workers_args]),
        (f"test (python {python_version})", test_args),
        ("test-scripts", ["test-scripts"]),
        ("verify-examples", ["verify-examples", "--all"]),
        ("check-dep-graph", ["check-dep-graph"]),
        ("check-version", ["check-version"] if can_diff else None),
        (
            "check-api",
            ["check-api", *check_api_workers_args] if can_diff else None,
        ),
        ("test-micropython", test_micropython_args),
        ("test-circuitpython", test_circuitpython_args),
    ]

    parallel_phases: list[tuple[str, Callable[[_Sink], int]]] = []
    skipped_phases: list[str] = []
    for label, args in parallel_specs:
        if args is None:
            skipped_phases.append(label)
            continue
        parallel_phases.append(
            (label, _preflight_phase_subprocess_factory(label, args)),
        )

    # Print skip notices up-front so the user sees them before the
    # parallel block.  Order: same as in the spec list above.
    for label in skipped_phases:
        print(f"== {label} ==")
        print(f"  SKIP: {base_reference} not reachable (fetch or set --base).")

    dispatcher = _pick_dispatcher(quiet=quiet)
    parallel_result, failing_label = _preflight_run_parallel_phases(
        parallel_phases,
        max_workers=phase_workers,
        dispatcher=dispatcher,
    )
    if parallel_result != 0:
        # The dispatcher already printed phase events and (in status /
        # quiet mode) the failing phase's transcript; finish with a
        # labeled banner so the failing phase survives interleaved-
        # output schedulers where its [FAIL] line scrolls past the
        # visible tail.
        if failing_label is not None:
            print(f"Preflight failed at: {failing_label}")
        else:
            print("Preflight failed.")  # pragma: no cover - defensive
        return parallel_result

    # Functional tests on real hardware run **after** the parallel
    # block and **serially** between themselves — both phases drive
    # the same boards via devices.yml defaults, so concurrent access
    # would deadlock.  See Decision 0048.
    if with_functional:
        functional_steps: list[tuple[str, Callable[[], int]]] = [
            ("test-libraries-functional", test_libraries_functional),
            ("test-workbench-functional", test_workbench_functional),
        ]
        for step_name, step in functional_steps:
            print(f"== {step_name} ==")
            result = step()
            if result != 0:
                print(f"Preflight failed at: {step_name}")
                return result

    # The on-device unit sweep also drives the boards, so it runs
    # serially here too — after functional, never concurrently.
    if with_device_unit:
        print("== test-unit-on-device ==")
        result = test_unit_on_device()
        if result != 0:
            print("Preflight failed at: test-unit-on-device")
            return result

    total_tests = _tally_pytest_counts(dispatcher.captured_outputs())
    if total_tests > 0:
        print(
            f"Preflight passed — required CI checks should pass.  "
            f"{total_tests} tests ran across all phases.",
        )
    else:
        print("Preflight passed — required CI checks should pass.")
    return 0


def _emit(sink: _Sink | None, message: str) -> None:
    """Write *message* to *sink* if set, otherwise to stdout.

    Lets functions like :func:`test_micropython` produce output
    that flows through a parallel-phase sink when run as a phase, or
    straight to the user when run standalone.
    """
    if sink is not None:
        sink.line(message)
    else:
        print(message)


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
    ``_test_runtime_compat`` helper provided — the plugin can't build
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

    Thin wrapper — see :func:`test_micropython` for the shape.
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
    exit_code, _failing_label = _run_parallel_phases(
        parallel_phases,
        dispatcher=_pick_dispatcher(quiet=False),
    )
    return exit_code


def _run_parallel_phases(
    phases: Sequence[tuple[str, Callable[[_Sink], int]]],
    *,
    dispatcher: _Dispatcher,
    max_workers: int | None = None,
) -> tuple[int, str | None]:
    """Run *phases* concurrently, routing output through *dispatcher*.

    Each phase callable receives a per-phase :class:`_Sink`; the sink
    forwards every line to the dispatcher (which decides what to do
    with it — buffer, prefix-and-print, or render in a status block)
    and also accumulates the full transcript on the sink object so the
    runner can hand it back to the dispatcher on phase completion.

    The dispatcher's lifecycle methods (``start`` / ``phase_started``
    / ``phase_done`` / ``finish``) are invoked from worker threads;
    implementations are expected to serialize their own output with a
    lock.

    Args:
        phases: ``(label, callable)`` pairs.  Each callable takes a
            :class:`_Sink` and returns the phase's exit code.
        dispatcher: Routes phase events + lines to the user.
        max_workers: Cap on concurrent phases.  ``None`` (default) is
            ``len(phases)`` — every phase runs at once.  Pass an
            integer to throttle for CPU / subprocess oversubscription.

    Returns:
        ``(exit_code, failing_label)`` — first non-zero exit code in
        submission order paired with its phase label, or ``(0, None)``
        when every phase succeeded.  The label lets callers print
        ``Preflight failed at: <label>``-style summaries that survive
        interleaved-output schedulers where the failing phase's
        ``[FAIL]`` line scrolls past the visible tail.
    """
    from concurrent.futures import ThreadPoolExecutor

    if not phases:
        return 0, None

    labels = [label for label, _ in phases]
    dispatcher.start(labels)

    def run_one(label: str, work: Callable[[_Sink], int]) -> tuple[str, int]:
        sink = _Sink(dispatcher, label)
        dispatcher.phase_started(label)
        try:
            exit_code = work(sink)
        except Exception as error:  # pragma: no cover - defensive
            sink.line(f"Phase {label!r} crashed: {error}")
            exit_code = 1
        dispatcher.phase_done(label, exit_code, sink.captured)
        return label, exit_code

    workers = max_workers if max_workers is not None else len(phases)
    workers = max(1, min(workers, len(phases)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(run_one, label, work) for label, work in phases
        ]
        results = [future.result() for future in futures]

    dispatcher.finish()

    for label, exit_code in results:
        if exit_code != 0:
            return exit_code, label
    return 0, None


def _subcommand_phase_factory(
    label: str,
    subcommand_args: list[str],
) -> Callable[[_Sink], int]:
    """Build a phase that subprocess-runs ``python scripts/run.py <args>``.

    The child runs with ``CHUMICRO_RAW_OUTPUT=1`` in its environment so
    its own dispatcher resolves to :class:`_RawDispatcher` — the child
    prints raw lines to its stdout, and our ``stream_subprocess`` reads
    them line-by-line and routes them through this phase's sink, where
    the parent's dispatcher decides how to render them (buffer, prefix,
    status-line).

    Subprocess re-invocation (rather than an in-process call) keeps
    each phase's resource footprint isolated and lets us cleanly
    capture *all* of the phase's output at the fd level — the
    in-process alternative would have to thread sinks through every
    helper that prints.  Decision 0048 chose the same shape (then for
    output-isolation reasons that this refactor solves differently);
    the design persists because per-phase isolation still has value.

    Args:
        label: Phase header (used in failure banners).
        subcommand_args: Arguments to append after ``[python,
            "scripts/run.py"]`` — e.g. ``["lint"]`` or ``["test",
            "--all", "--coverage-threshold", "94"]``.
    """
    command = [PYTHON, "scripts/run.py", *subcommand_args]

    def run_phase(sink: _Sink) -> int:
        sink.line(f"+ {' '.join(command)}")
        environment = {**os.environ, _RAW_OUTPUT_ENV_VAR: "1"}
        exit_code, _ = stream_subprocess(
            command, cwd=ROOT, environment=environment, on_line=sink.line,
        )
        if exit_code != 0:
            sink.line(f"Phase failed: {label}")
        return exit_code

    return run_phase


# Backward-compatible alias kept for tests that monkeypatch this seam.
_preflight_phase_subprocess_factory = _subcommand_phase_factory


_PYTEST_RESULT_LINE = re.compile(
    r"^(?:=+\s*|\S+:\s+)(?P<passed>\d+)\s+passed"
    r"(?:,\s+\d+\s+(?:skipped|deselected|warnings?))*"
    r"(?:\s+across\s+\d+\s+librar(?:y|ies))?"
    r"\s+in\s+\d+\.\d+s",
    re.MULTILINE,
)


def _tally_pytest_counts(captured_outputs: dict[str, str]) -> int:
    """Sum every ``N passed ... in Xs`` summary line across phase outputs.

    Matches both the raw pytest summary (``=== N passed in Xs ===``,
    used by phases that bypass the per-library filter like
    ``test-scripts``) and the rolled-up phase summary that
    :func:`_format_pytest_phase_summary` emits (``<phase>: N passed
    across M libraries in Xs``).  Counts every match so the end-of-run
    total reflects all tests actually executed — host CPython +
    MicroPython unix-port + CircuitPython unix-port.

    Returns ``0`` when no pytest result lines are found (e.g. the
    dispatcher doesn't buffer output, like the live interleave mode).
    """
    total = 0
    for captured in captured_outputs.values():
        for match in _PYTEST_RESULT_LINE.finditer(captured):
            total += int(match.group("passed"))
    return total


def _preflight_run_parallel_phases(
    phases: Sequence[tuple[str, Callable[[_Sink], int]]],
    *,
    max_workers: int = _DEFAULT_PREFLIGHT_PHASE_PARALLEL_WORKERS,
    dispatcher: _Dispatcher | None = None,
) -> tuple[int, str | None]:
    """Dispatch the parallel preflight phase block.

    Thin wrapper over :func:`_run_parallel_phases` that exists as a
    named seam so tests can monkeypatch the parallel block without
    forking the subprocess invocations on every preflight test.

    Returns ``(exit_code, failing_label)`` straight through from the
    underlying runner.
    """
    return _run_parallel_phases(
        phases,
        dispatcher=dispatcher or _pick_dispatcher(quiet=False),
        max_workers=max_workers,
    )


def test_functional(
    *,
    verbose: bool = False,
    exit_first: bool = False,
) -> int:
    """Run every hardware-gated functional suite end-to-end.

    Composes :func:`test_libraries_functional` (library code on
    connected MCUs) and :func:`test_workbench_functional` (host-side
    CPython tests that drive a board).  Both phases use ``devices.yml``
    defaults — for narrower runs, call the individual commands directly.
    """
    steps: list[tuple[str, Callable[[], int]]] = [
        ("test-libraries-functional", test_libraries_functional),
        (
            "test-workbench-functional",
            lambda: test_workbench_functional(
                verbose=verbose, exit_first=exit_first,
            ),
        ),
    ]

    for step_name, step in steps:
        print(f"== {step_name} ==")
        result = step()
        if result != 0:
            print(f"Step failed: {step_name}")
            return result

    return 0


def test_libraries_functional(
    runtime: str | None = None,
    micropython_device: str | None = None,
    circuitpython_device: str | None = None,
    library: str | None = None,
    file_filter: str | None = None,
    function_filter: str | None = None,
    deploy_mode: str | None = None,
) -> int:
    """Run functional tests on connected devices.

    Thin wrapper that invokes ``pytest libraries/<name>/functional_tests/``
    with the ``--chumicro-*`` flags the ``chumicro-pytest-device``
    plugin exposes.  The plugin owns collection, routing, transport
    caching, and the PR-summary block — the IDE play-button path
    uses exactly the same hooks, so CLI and IDE runs are byte-for-byte
    equivalent in behavior (device selection, mode overrides,
    reporting).

    Args:
        runtime: Override ``defaults.ide_runtime`` (``micropython`` /
            ``circuitpython`` / ``both``).
        micropython_device: Override ``defaults.micropython`` device ID.
        circuitpython_device: Override ``defaults.circuitpython`` device ID.
        library: Limit to one library's ``functional_tests/``.
        file_filter: Substring added to pytest ``-k`` to narrow by test
            file name.  Composed with *function_filter* via ``and``.
        function_filter: Substring added to pytest ``-k`` to narrow by
            test-function name.  Composed with *file_filter* via ``and``.
        deploy_mode: Override the per-device deploy mode (``ram`` /
            ``flash``).  Falls back to ``devices.yml`` per-device or
            defaults when omitted.

    Returns:
        The pytest exit code — ``0`` on all-pass, ``1`` on failures,
        ``2`` for configuration problems (unknown library, collection
        errors).
    """
    if library is not None:
        library_dir = ROOT / "libraries" / library
        if not (library_dir / "functional_tests").is_dir():
            print(
                f"No functional_tests/ directory found for "
                f"--library {library!r}."
            )
            return 2
        suites = [library_dir / "functional_tests"]
    else:
        suites = [
            library_dir / "functional_tests"
            for library_dir in discover_library_dirs()
            if (library_dir / "functional_tests").is_dir()
        ]
    if not suites:
        print("No functional tests to run.")
        return 0

    keyword_parts: list[str] = []
    if file_filter:
        keyword_parts.append(file_filter)
    if function_filter:
        keyword_parts.append(function_filter)

    command = [PYTHON, "-m", "pytest", *[str(path) for path in suites]]
    if keyword_parts:
        command.extend(["-k", " and ".join(keyword_parts)])
    if runtime is not None:
        command.extend(["--runtime", runtime])
    if micropython_device is not None:
        command.extend(["--micropython-device", micropython_device])
    if circuitpython_device is not None:
        command.extend(["--circuitpython-device", circuitpython_device])
    if deploy_mode is not None:
        command.extend(["--deploy-mode", deploy_mode])
    command.extend([
        "--pr-summary",
        "--pr-summary-command",
        _format_test_libraries_functional_command(
            runtime, micropython_device, circuitpython_device,
            library, file_filter, function_filter, deploy_mode,
        ),
    ])
    return run_command(command, environment=pythonpath_environment())


def _format_test_libraries_functional_command(
    runtime: str | None,
    micropython_device: str | None,
    circuitpython_device: str | None,
    library: str | None,
    file_filter: str | None,
    function_filter: str | None,
    deploy_mode: str | None,
) -> str:
    """Reconstruct the ``test-libraries-functional`` CLI invocation from its args.

    Only includes flags the caller explicitly passed (non-``None`` values)
    so the rendered command matches what the user actually typed.  Used
    by the plugin's PR-summary block to render the ``- Command:`` line.
    """
    parts = ["python scripts/run.py test-libraries-functional"]
    if runtime is not None:
        parts.append(f"--runtime {runtime}")
    if micropython_device is not None:
        parts.append(f"--micropython-device {micropython_device}")
    if circuitpython_device is not None:
        parts.append(f"--circuitpython-device {circuitpython_device}")
    if library is not None:
        parts.append(f"--library {library}")
    if file_filter is not None:
        parts.append(f"--file {file_filter}")
    if function_filter is not None:
        parts.append(f"--function {function_filter}")
    if deploy_mode is not None:
        parts.append(f"--deploy-mode {deploy_mode}")
    return " ".join(parts)


def _library_has_cross_runtime_unit_suite(library_dir: Path) -> bool:
    """True when ``library_dir/tests`` holds a device-unit-eligible file.

    A file is eligible for the on-device sweep when its in-file
    markers put it in the device lane: not CPython-only
    (``__chumicro_runtimes__ = ("cpython",)``) and not host-only
    (``__chumicro_host_only__ = True``).  The lane is read via the
    shared ``chumicro_deploy`` marker predicate — the same one the
    pytest-device collector uses — so this orchestration pre-filter
    and the collector never disagree (no duplicated filename rule).
    """
    from chumicro_deploy import (  # noqa: PLC0415 — deferred heavy import
        is_host_only_test,
        read_runtime_marker,
    )

    tests_dir = library_dir / "tests"
    if not tests_dir.is_dir():
        return False
    for path in tests_dir.glob("test_*.py"):
        if is_host_only_test(path):
            continue
        marker = read_runtime_marker(path)
        if marker is not None and not any(
            name == "circuitpython" or name.startswith("micropython")
            for name in marker
        ):
            # CPython-only (no device runtime in the marker) — not swept.
            continue
        return True
    return False


def _library_pip_name(library_dir: Path) -> str:
    """Return the library's ``[project].name`` (the requires_flash key).

    Falls back to the ``chumicro-<dir>`` convention if the pyproject is
    unreadable — only used to decide whether the resolution unit is
    itself in the flagged set, so the convention is a safe default.
    """
    import tomllib  # noqa: PLC0415 — deferred; this task is rarely run

    pyproject = library_dir / "pyproject.toml"
    try:
        with pyproject.open("rb") as handle:
            name = tomllib.load(handle).get("project", {}).get("name")
    except (OSError, tomllib.TOMLDecodeError):
        name = None
    return name or f"chumicro-{library_dir.name.replace('_', '-')}"


def test_unit_on_device(
    runtime: str | None = None,
    micropython_device: str | None = None,
    circuitpython_device: str | None = None,
    deploy_mode: str | None = None,
    library: str | None = None,
    per_file: bool = False,
) -> int:
    """Run the cross-runtime *unit* suite on real boards (the sweep).

    For each library, resolves the deploy mode through the one shared
    policy with **own-src** ``staged_files`` scoping (a dependency's
    data file must not poison a light dependent's suite) and the full
    transitive ``requires_flash`` closure; then groups libraries by
    resolved mode and runs each group as one single-mode
    ``--target device-unit`` pytest session per runtime.  A light
    library stays in the fast RAM session; a ``requires_flash`` or
    data-file library lands in a flash session — only that library's
    suite switches, not the whole sweep.

    The sweep's last-resort mode preference is **RAM** (its purpose is
    RAM-capable on-device validation; Decision 0047's flash-default
    footgun does not apply to a deliberate dev sweep).  ``--deploy-mode``
    overrides that preference; unlike the functional path the sweep
    does not inherit ``devices.yml``'s ``deploy_mode`` (that is tuned
    for app-shaped functional deploys).  Behavioral pass/fail only —
    no coverage gating (``coverage.py`` cannot trace MP / CP bytecode).

    Args:
        runtime: ``micropython`` / ``circuitpython`` / ``both``
            (default: both).
        micropython_device: Override the MicroPython target device ID.
        circuitpython_device: Override the CircuitPython target ID.
        deploy_mode: Override the RAM preference for every library
            (``ram`` / ``flash``); the per-library rule still applies.
        library: Limit the sweep to one library's unit suite.
        per_file: Soft-reset before each test *file* (not just each
            library) in flash/copy sessions, so a large class-organized
            module runs on a fresh interpreter.  Opt-in — slower; for
            large suites on a 256 KB board.  No-op for RAM sessions
            (they already reset per file).

    Returns:
        ``0`` all-pass, ``1`` test failures, ``2`` configuration
        problems.  Cleanly returns ``0`` when no board is configured
        for a target runtime (matches the functional path).
    """
    from chumicro_deploy import (  # noqa: PLC0415 — deferred heavy import
        DeviceCaps,
        DeviceConfigError,
        find_libraries_requiring_flash,
        load_device_registry,
        resolve_deploy_mode,
    )
    from chumicro_pytest_device._test_runner import (  # noqa: PLC0415
        resolve_library_source_dirs,
    )

    libraries_root = ROOT / "libraries"
    if library is not None:
        candidate = libraries_root / library
        if not _library_has_cross_runtime_unit_suite(candidate):
            print(f"No cross-runtime unit suite for --library {library!r}.")
            return 2
        library_dirs = [candidate]
    else:
        library_dirs = [
            directory
            for directory in discover_library_dirs()
            if _library_has_cross_runtime_unit_suite(directory)
        ]
    if not library_dirs:
        print("No on-device unit suites to run.")
        return 0

    try:
        devices, defaults = load_device_registry(workspace_root=ROOT)
    except DeviceConfigError as error:
        print(f"Skipping on-device unit sweep: {error}")
        return 0
    devices_by_id = {entry.identifier: entry for entry in devices}

    if runtime in (None, "both"):
        target_runtimes = ["micropython", "circuitpython"]
    else:
        target_runtimes = [runtime]
    device_override = {
        "micropython": micropython_device,
        "circuitpython": circuitpython_device,
    }

    configured = deploy_mode or "ram"
    worst_exit = 0
    ran_anything = False

    for target_runtime in target_runtimes:
        device_id = device_override[target_runtime] or getattr(
            defaults, target_runtime,
        )
        device_entry = devices_by_id.get(device_id) if device_id else None
        if device_entry is None:
            print(
                f"No {target_runtime} device configured "
                f"(devices.yml defaults.{target_runtime}); "
                f"skipping its unit sweep.",
            )
            continue

        device_capabilities = DeviceCaps(
            supports_ram_mode=device_entry.supports_ram_mode,
        )
        libraries_by_mode: dict[str, list[Path]] = {}
        for library_dir in library_dirs:
            own_source = library_dir / "src"
            own_files = [
                path.name
                for path in own_source.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
            ]
            closure_dirs = resolve_library_source_dirs(
                library_dir, libraries_root=libraries_root,
            )
            mode, message = resolve_deploy_mode(
                configured,
                staged_files=own_files,
                device_caps=device_capabilities,
                requires_flash_libs=find_libraries_requiring_flash(
                    closure_dirs,
                ),
                resolution_unit=_library_pip_name(library_dir),
                force=None,
            )
            if message is not None:
                print(f"[{library_dir.name} → {target_runtime}] {message}")
            libraries_by_mode.setdefault(mode, []).append(library_dir)

        # Flash group before RAM so the slower, wear-incurring session
        # runs first and a RAM-group failure isn't masked by flash I/O.
        for session_mode in ("flash", "ram"):
            group = libraries_by_mode.get(session_mode)
            if not group:
                continue
            ran_anything = True
            command = [
                PYTHON, "-m", "pytest",
                *[str(directory / "tests") for directory in group],
                "--target", "device-unit",
                "--runtime", target_runtime,
                f"--{target_runtime}-device", device_entry.identifier,
                "--deploy-mode", session_mode,
                "--pr-summary",
                "--pr-summary-command",
                (
                    f"python scripts/run.py test-unit-on-device "
                    f"--runtime {target_runtime} "
                    f"--deploy-mode {session_mode}"
                    + (" --per-file" if per_file else "")
                ),
            ]
            if per_file:
                command.append("--per-file")
            print(
                f"== on-device unit sweep: {target_runtime} / "
                f"{session_mode} ({len(group)} libraries) ==",
            )
            exit_code = run_command(
                command, environment=pythonpath_environment(),
            )
            worst_exit = worst_exit or exit_code

    if not ran_anything:
        print("No on-device unit sweep ran (no target devices).")
        return 0
    return worst_exit


def test_workbench_functional(
    workbench: str | None = None,
    file_filter: str | None = None,
    function_filter: str | None = None,
    verbose: bool = False,
    exit_first: bool = False,
) -> int:
    """Run functional tests for workbench packages against real hardware.

    Counterpart to :func:`test_libraries_functional` for workbench packages.  Each
    ``workbench/<name>/functional_tests/`` directory is a plain
    host-side pytest suite that drives a connected board through the
    public ``chumicro_deploy`` API (or each workbench's own entrypoint)
    — no test-harness plugin routes these, since workbench code is
    CPython-only and talks to hardware itself.

    Device selection happens inside each suite's ``conftest.py``
    (typically by reading ``devices.yml``), so this task exposes no
    runtime or device flags.  Change the default board by editing
    ``devices.yml`` defaults, or pass through the fixtures the test
    suite documents.

    Args:
        workbench: Name of one workbench package (``deploy``, etc.) to
            limit the run to.  ``None`` runs every workbench package
            that ships a ``functional_tests/`` directory.
        file_filter: Substring passed to pytest ``-k`` that narrows
            collection to test files whose filename contains this
            string.  Composed with *function_filter* via ``and``.
        function_filter: Substring passed to pytest ``-k`` that
            narrows collection to test functions whose name contains
            this string.  Composed with *file_filter* via ``and``.
        verbose: Forward ``-v`` to pytest for per-test PASS/FAIL lines.
        exit_first: Forward ``-x`` to pytest so the run stops at the
            first failure.

    Returns:
        ``0`` when every selected suite passes; the first non-zero
        pytest exit code otherwise.  ``0`` with a warning when no
        workbench package has a ``functional_tests/`` directory.
    """
    workbench_dirs = discover_workbench_dirs()
    if workbench is not None:
        workbench_dirs = [
            package_dir for package_dir in workbench_dirs
            if package_dir.name == workbench
        ]
        if not workbench_dirs:
            print(f"No workbench package matches --workbench {workbench!r}.")
            return 1

    suites = [
        package_dir / "functional_tests"
        for package_dir in workbench_dirs
        if (package_dir / "functional_tests").is_dir()
    ]
    if not suites:
        scope = f"--workbench {workbench!r}" if workbench else "any workbench package"
        print(f"No functional_tests/ directory found for {scope}.")
        return 0

    keyword_parts: list[str] = []
    if file_filter:
        keyword_parts.append(file_filter)
    if function_filter:
        keyword_parts.append(function_filter)

    extra_args: list[str] = []
    if exit_first:
        extra_args.append("-x")
    if verbose:
        extra_args.append("-v")
    if keyword_parts:
        extra_args.extend(["-k", " and ".join(keyword_parts)])

    # Unlike host-only ``test``, this task does not pass ``-W error``
    # — hardware-interacting tests routinely surface warnings from
    # upstream libraries (mpremote's mount/unmount leaves a file
    # finalizer; pyserial's cleanup) that are out of our control.
    # Matches ``test-libraries-functional``'s behavior for the same reason.
    first_failure = 0
    environment = pythonpath_environment()
    for suite in suites:
        print(f"== test-workbench-functional ({suite.parent.name}) ==")
        result = run_command(
            [
                PYTHON, "-m", "pytest",
                str(suite),
                *extra_args,
            ],
            environment=environment,
        )
        if result != 0 and first_failure == 0:
            first_failure = result
    return first_failure


def validate_mip(
    bundle_repo: str | None = None,
    libraries: str | None = None,
    micropython_binary: str | None = None,
    staging_dir: str | None = None,
) -> int:
    """Validate mip install and import for bundle packages.

    Tests both .py and .mpy6 formats against a live bundle repository
    or a locally staged bundle directory.
    Requires a MicroPython unix-port binary (auto-detected or explicit).
    """
    library_names = (
        [name.strip() for name in libraries.split(",") if name.strip()]
        if libraries else None
    )
    if library_names is None:
        # Auto-discover publishable libraries.
        library_names = [
            package_dir.name for package_dir in discover_library_dirs()
        ]
    if not library_names:
        print("No libraries found to validate.")
        return 1

    if staging_dir:
        from validate_mip_install import validate_local_staging
        return validate_local_staging(
            staging_dir=staging_dir,
            library_names=library_names,
            binary=micropython_binary,
        )

    if bundle_repo:
        from validate_mip_install import validate_mip_install
        return validate_mip_install(
            bundle_repo=bundle_repo,
            library_names=library_names,
            binary=micropython_binary,
        )

    print("Either --bundle-repo or --staging-dir is required.")
    return 1


def check_version(*, base: str = "origin/main") -> int:
    """Check VERSION enforcement for changed libraries (PR check)."""
    from check_version import main as check_version_main
    return check_version_main(["--base", base])


def check_api(
    *,
    max_workers: int = _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    base: str = "origin/main",
) -> int:
    """Check API breakages against last release tag (PR check)."""
    from check_api import main as check_api_main
    return check_api_main(
        ["--base", base, "--max-workers", str(max_workers)],
    )


def check_dep_graph() -> int:
    """Verify the committed dependency-graph SVG matches the current
    ``libraries/*/pyproject.toml`` deps.  Fails if a contributor changed
    a library's deps without re-running ``python scripts/render_dep_graph.py``
    and committing the regenerated SVG.
    """
    from render_dep_graph import main as render_dep_graph_main
    return render_dep_graph_main(["--check"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _scope_parent() -> argparse.ArgumentParser:
    """Parent parser providing ``--all`` / ``--libraries`` scope flags."""
    parent = argparse.ArgumentParser(add_help=False)
    group = parent.add_mutually_exclusive_group()
    group.add_argument(
        "--all", action="store_true", dest="all_packages",
        help="run for all packages",
    )
    group.add_argument(
        "--libraries", metavar="LIB,...",
        help="run for specific packages (comma-separated names)",
    )
    return parent


def _binary_parent() -> argparse.ArgumentParser:
    """Parent parser providing runtime binary override flags."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--micropython-binary", metavar="PATH",
        help="path to MicroPython binary (overrides auto-detection)",
    )
    parent.add_argument(
        "--circuitpython-binary", metavar="PATH",
        help="path to CircuitPython binary (overrides auto-detection)",
    )
    return parent


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


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="python scripts/run.py",
        description="Repository-level task runner for humans, agents, and CI.",
    )
    subparsers = parser.add_subparsers(dest="task")
    scope = _scope_parent()
    binary = _binary_parent()

    # No-arg tasks
    subparsers.add_parser("setup", help="install dependencies and regenerate IDE configuration")
    subparsers.add_parser("sync-ide", help="regenerate IDE configuration files")
    subparsers.add_parser("lint", help="run Ruff across the workspace")
    # ``add-device`` is a pass-through shim around ``chumicro-workspace
    # add-device`` — keeps the mono-repo's ``run.py`` as the single
    # entry-point contributors learn while reusing the workspace
    # package's hardware-probe + three-zone-aware writer.
    # ``parse_known_args`` semantics: every argv after ``add-device``
    # is forwarded verbatim to ``python -m chumicro_workspace
    # add-device <argv>`` so flag drift is impossible.
    subparsers.add_parser(
        "add-device",
        add_help=False,
        help=(
            "register a board in devices.yml (probes hardware identity, "
            "fills in defaults on first registration); pass --help after "
            "the subcommand for the full chumicro-workspace flag list"
        ),
    )
    build_parser = subparsers.add_parser(
        "build", help="build all publishable packages",
    )
    build_parser.add_argument(
        "--package-workers", type=int, metavar="N",
        default=_DEFAULT_PACKAGE_PARALLEL_WORKERS,
        help=(
            f"cap on concurrent per-package build subprocesses "
            f"(default: {_DEFAULT_PACKAGE_PARALLEL_WORKERS} for this host)"
        ),
    )
    build_parser.add_argument(
        "--quiet", action="store_true",
        help="buffer per-phase output; replay full transcript at end",
    )
    preflight_parser = subparsers.add_parser(
        "preflight", parents=[binary],
        help="lint + test + examples + compatibility + build",
    )
    preflight_parser.add_argument(
        "--coverage-threshold", type=int, metavar="PCT",
        help=(
            "override coverage fail-under percentage "
            "(default: from pyproject.toml)"
        ),
    )
    preflight_parser.add_argument(
        "--with-functional", action="store_true",
        help=(
            "also run test-libraries-functional and "
            "test-workbench-functional after the unit-test phases "
            "(requires connected hardware)"
        ),
    )
    preflight_parser.add_argument(
        "--with-device-unit", action="store_true",
        help=(
            "also run test-unit-on-device (the cross-runtime unit "
            "suite on connected boards) after the functional tail "
            "(requires connected hardware)"
        ),
    )
    preflight_parser.add_argument(
        "--phase-workers", type=int, metavar="N",
        default=_DEFAULT_PREFLIGHT_PHASE_PARALLEL_WORKERS,
        help=(
            f"cap on concurrent preflight phases "
            f"(default: {_DEFAULT_PREFLIGHT_PHASE_PARALLEL_WORKERS} for this host)"
        ),
    )
    preflight_parser.add_argument(
        "--package-workers", type=int, metavar="N",
        default=_DEFAULT_PACKAGE_PARALLEL_WORKERS,
        help=(
            f"cap on concurrent per-package subprocesses inside each "
            f"phase that fans out by package "
            f"(default: {_DEFAULT_PACKAGE_PARALLEL_WORKERS} for this host)"
        ),
    )
    preflight_parser.add_argument(
        "--slow-test-threshold-cpython", type=float, metavar="SECONDS",
        default=_DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
        help=(
            f"warn-only threshold for surfacing slow CPython unit tests "
            f"(default: {_DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON:.1f}s)"
        ),
    )
    preflight_parser.add_argument(
        "--slow-test-threshold-unix-port", type=float, metavar="SECONDS",
        default=_DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
        help=(
            f"warn-only threshold for surfacing slow unix-port tests "
            f"(default: {_DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT:.1f}s)"
        ),
    )
    preflight_parser.add_argument(
        "--quiet", action="store_true",
        help=(
            "buffer per-phase output; replay full transcript under "
            "== <phase> == headers in submission order at end "
            "(useful for log capture and agent runs)"
        ),
    )
    subparsers.add_parser("prepare-micropython", help="prepare MicroPython unix-port")
    subparsers.add_parser("prepare-circuitpython", help="prepare CircuitPython unix-port")
    subparsers.add_parser(
        "prepare-mpy-cross",
        help="build mpy-cross compilers for both runtimes (no unix-port)",
    )
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
    test_functional_parser = subparsers.add_parser(
        "test-functional",
        description=(
            "Run every hardware-gated functional suite in the workspace: "
            "test-libraries-functional (library code on connected MCUs) "
            "followed by test-workbench-functional (host-side workbench "
            "tests that drive a board).  Both phases use devices.yml "
            "defaults — for narrower runs, use the individual commands."
        ),
        help=(
            "run all hardware-gated functional tests "
            "(libraries + workbench, devices.yml defaults)"
        ),
    )
    test_functional_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="verbose test output (forwarded to test-workbench-functional)",
    )
    test_functional_parser.add_argument(
        "-x", "--exit-first", action="store_true",
        help="stop the workbench phase on first failure",
    )
    test_libraries_functional_parser = subparsers.add_parser(
        "test-libraries-functional",
        description=(
            "Run functional tests on connected devices. When runtime and "
            "runtime-specific device flags are omitted, the command uses the default target "
            "device(s) from devices.yml. Pass --runtime to override the "
            "runtime set, and --micropython-device / --circuitpython-device "
            "to override the default board for each runtime."
        ),
        help=(
            "run functional tests on connected devices "
            "(uses devices.yml defaults when unfiltered)"
        ),
    )
    test_libraries_functional_parser.add_argument(
        "--runtime",
        choices=["micropython", "circuitpython", "both"],
        help=(
            "override the default runtime set, or use 'both' for the "
            "defaults-backed dual-runtime target set"
        ),
    )
    test_libraries_functional_parser.add_argument(
        "--micropython-device",
        help="override the default MicroPython device ID",
    )
    test_libraries_functional_parser.add_argument(
        "--circuitpython-device",
        help="override the default CircuitPython device ID",
    )
    test_libraries_functional_parser.add_argument(
        "--library",
        help="limit to one library's functional tests",
    )
    test_libraries_functional_parser.add_argument(
        "--file",
        dest="file_filter",
        help="limit to test files whose name contains this substring",
    )
    test_libraries_functional_parser.add_argument(
        "--function",
        dest="function_filter",
        help="limit to test functions whose name contains this substring",
    )
    test_libraries_functional_parser.add_argument(
        "--deploy-mode",
        dest="deploy_mode",
        choices=["ram", "flash"],
        default=None,
        help="deploy mode: ram (default, no flash wear) or flash (persistent). "
             "Overrides the per-device deploy_mode in devices.yml.",
    )
    test_workbench_functional_parser = subparsers.add_parser(
        "test-workbench-functional",
        description=(
            "Run functional tests for workbench packages against "
            "connected hardware.  Counterpart to test-libraries-functional, for "
            "the host-only CPython tools under workbench/ that drive "
            "boards through the public chumicro_deploy API.  Device "
            "selection lives inside each suite's conftest.py — "
            "change the target board via devices.yml defaults."
        ),
        help=(
            "run workbench functional tests "
            "(hardware-gated via devices.yml fixtures)"
        ),
    )
    test_workbench_functional_parser.add_argument(
        "--workbench",
        help="limit to one workbench package (e.g. deploy)",
    )
    test_workbench_functional_parser.add_argument(
        "--file",
        dest="file_filter",
        help="limit to test files whose name contains this substring",
    )
    test_workbench_functional_parser.add_argument(
        "--function",
        dest="function_filter",
        help="limit to test functions whose name contains this substring",
    )
    test_workbench_functional_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="verbose test output",
    )
    test_workbench_functional_parser.add_argument(
        "-x", "--exit-first", action="store_true",
        help="stop on first failure",
    )

    test_unit_on_device_parser = subparsers.add_parser(
        "test-unit-on-device",
        description=(
            "Run the cross-runtime libraries/<name>/tests suite on real "
            "boards.  Resolves each library's deploy mode (own-src "
            "scoping, RAM-preferred), groups libraries by mode, and "
            "runs one single-mode session per runtime: light libraries "
            "ride a fast RAM session, requires_flash / data-file "
            "libraries land in a flash session.  Behavioral pass/fail "
            "only — no coverage gating."
        ),
        help=(
            "run the cross-runtime unit suite on connected boards "
            "(RAM-preferred, mode-grouped; the on-device unit sweep)"
        ),
    )
    test_unit_on_device_parser.add_argument(
        "--runtime",
        choices=["micropython", "circuitpython", "both"],
        help="runtime set to sweep (default: both)",
    )
    test_unit_on_device_parser.add_argument(
        "--micropython-device",
        help="override the MicroPython target device ID",
    )
    test_unit_on_device_parser.add_argument(
        "--circuitpython-device",
        help="override the CircuitPython target device ID",
    )
    test_unit_on_device_parser.add_argument(
        "--deploy-mode",
        dest="deploy_mode",
        choices=["ram", "flash"],
        default=None,
        help=(
            "override the RAM mode preference for every library "
            "(the per-library requires_flash / data-file rule still "
            "applies); default preference is ram"
        ),
    )
    test_unit_on_device_parser.add_argument(
        "--library",
        help="limit the sweep to one library's unit suite",
    )
    test_unit_on_device_parser.add_argument(
        "--per-file",
        dest="per_file",
        action="store_true",
        help=(
            "soft-reset before each test file (not just each library) "
            "in flash/copy sessions, so a large class-organized module "
            "runs on a fresh interpreter; opt-in, slower, for large "
            "suites on a 256 KB board (no-op for RAM sessions)"
        ),
    )

    check_version_parser = subparsers.add_parser(
        "check-version", help="check VERSION enforcement for changed libraries",
    )
    check_version_parser.add_argument(
        "--base", default="origin/main",
        help="git ref to diff against (default: origin/main)",
    )
    check_api_parser = subparsers.add_parser(
        "check-api", help="check API breakages against last release tag",
    )
    check_api_parser.add_argument(
        "--base", default="origin/main",
        help="git ref to detect changed packages (default: origin/main)",
    )
    check_api_parser.add_argument(
        "--max-workers", type=int, metavar="N",
        default=_DEFAULT_PACKAGE_PARALLEL_WORKERS,
        help=(
            f"cap on concurrent griffe subprocesses "
            f"(default: {_DEFAULT_PACKAGE_PARALLEL_WORKERS})"
        ),
    )
    subparsers.add_parser(
        "check-dep-graph",
        help="verify support/docs/dependency-graph.svg matches current pyproject deps",
    )

    validate_mip_parser = subparsers.add_parser(
        "validate-mip",
        help="validate mip install + import against a bundle repo or local staging",
    )
    validate_mip_source = validate_mip_parser.add_mutually_exclusive_group(
        required=True,
    )
    validate_mip_source.add_argument(
        "--bundle-repo",
        help="bundle repository name (e.g. ChuMicro-Bundle-Experimental)",
    )
    validate_mip_source.add_argument(
        "--staging-dir",
        help="path to a locally staged bundle directory",
    )
    validate_mip_parser.add_argument(
        "--libraries",
        help="comma-separated library names (default: all)",
    )
    validate_mip_parser.add_argument(
        "--micropython-binary", metavar="PATH",
        help="path to MicroPython binary (overrides auto-detection)",
    )

    test_scripts_parser = subparsers.add_parser(
        "test-scripts", help="run scripts/ infrastructure tests",
    )
    test_scripts_parser.add_argument(
        "-x", "--exit-first", action="store_true",
        help="stop on first failure",
    )
    test_scripts_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="verbose test output",
    )

    deploy_parser = subparsers.add_parser(
        "docs-deploy",
        help="deploy versioned docs to gh-pages (used by CI)",
    )
    deploy_parser.add_argument(
        "--channel", choices=["experimental", "stable"],
        required=True,
        help="docs channel to deploy",
    )
    deploy_parser.add_argument(
        "--libraries",
        help="comma-separated list of libraries to deploy (default: all)",
    )

    # Scoped tasks
    test_parser = subparsers.add_parser(
        "test", parents=[scope],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="CPython tests (only changed packages by default)",
        epilog=(
            "examples:\n"
            "  run.py test                                                "
            "# changed packages\n"
            "  run.py test --all                                          "
            "# all packages\n"
            "  run.py test -k timing/test_heartbeat                      "
            "# by library and test\n"
            "  run.py test -k timing/test_ticks/ticks_add                "
            "# by library, file, and test\n"
            "  run.py test -k timing/ticks_diff,runner/task_handle  "
            "# per-library filters\n"
            "  run.py test --no-cov -x                                   "
            "# quick, stop on failure"
        ),
    )
    test_parser.add_argument(
        "-k", dest="filter_expression", metavar="FILTER",
        help=(
            "library/test or library/file/test "
            "(comma-separated for multiple)"
        ),
    )
    test_parser.add_argument(
        "-x", "--exit-first", action="store_true",
        help="stop on first failure",
    )
    test_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="verbose test output",
    )
    test_parser.add_argument(
        "--no-cov", action="store_true",
        help="skip coverage collection",
    )
    test_parser.add_argument(
        "--coverage-threshold", type=int, metavar="PCT",
        help=(
            "override coverage fail-under percentage "
            "(default: from pyproject.toml)"
        ),
    )
    test_parser.add_argument(
        "--elevated-packages", metavar="NAMES",
        help=(
            "comma-separated package names that should use "
            "--coverage-threshold; other packages keep the pyproject.toml "
            "default.  Used by preflight to enforce a higher bar on "
            "changed libraries without failing on pre-existing coverage "
            "in untouched ones."
        ),
    )
    test_parser.add_argument(
        "--package-workers", type=int, metavar="N",
        default=_DEFAULT_PACKAGE_PARALLEL_WORKERS,
        help=(
            f"cap on concurrent per-package pytest subprocesses "
            f"(default: {_DEFAULT_PACKAGE_PARALLEL_WORKERS} for this host)"
        ),
    )
    test_parser.add_argument(
        "--slow-test-threshold-cpython", type=float, metavar="SECONDS",
        default=_DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
        help=(
            f"warn-only threshold for surfacing slow CPython unit tests "
            f"(default: {_DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON:.1f}s)"
        ),
    )
    test_parser.add_argument(
        "--quiet", action="store_true",
        help="buffer per-phase output; replay full transcript at end",
    )
    subparsers.add_parser("verify-examples", parents=[scope], help="import-check examples")

    docs_parser = subparsers.add_parser("docs", parents=[scope], help="build library docs")
    docs_parser.add_argument(
        "--serve", action="store_true", help="start live-reload dev server",
    )
    docs_parser.add_argument(
        "--package-workers", type=int, metavar="N",
        default=_DEFAULT_PACKAGE_PARALLEL_WORKERS,
        help=(
            f"cap on concurrent per-library docs builds "
            f"(default: {_DEFAULT_PACKAGE_PARALLEL_WORKERS} for this host)"
        ),
    )
    docs_parser.add_argument(
        "--quiet", action="store_true",
        help="buffer per-phase output; replay full transcript at end",
    )

    subparsers.add_parser(
        "docs-preview", parents=[scope],
        help="deploy docs to local gh-pages and serve versioned site",
    )

    # new-library
    new_library_parser = subparsers.add_parser("new-library", help="scaffold a new library")
    new_library_parser.add_argument("name", help="library name (e.g. gpio)")

    return parser


def _resolve_scoped_packages(args) -> list[Path]:
    """Resolve package directories for tasks that accept scope flags.

    Args:
        args: Parsed CLI arguments (must have ``all_packages`` and
            ``libraries``).
    """
    return resolve_scope(
        all_packages=args.all_packages, libraries=args.libraries,
    )


def _resolve_optional_scope(args) -> list[Path] | None:
    """Resolve package scope only when explicit scope flags were provided."""
    if args.all_packages or args.libraries:
        return _resolve_scoped_packages(args)
    return None


def main(argv: list[str]) -> int:
    """Dispatch a named repository-level task."""
    # ``add-device`` and ``deploy-example`` are pass-through shims
    # around their workspace counterparts.  Peeled off before argparse
    # so the workspace package's flag sets (which evolve independently
    # of run.py) flow through verbatim.
    if len(argv) >= 2 and argv[1] in ("add-device", "deploy-example"):
        return subprocess.run(
            [PYTHON, "-m", "chumicro_workspace", argv[1], *argv[2:]],
            check=False,
        ).returncode

    parser = _build_parser()
    args = parser.parse_args(argv[1:])

    if not args.task:
        parser.print_help()
        return 1

    # --- scoped tasks (--all / --libraries) ---

    if args.task == "test":
        if args.filter_expression and "/" in args.filter_expression:
            # Library-scoped -k provides its own library scope via the
            # filter expression, so skip resolve_scope() to avoid a
            # misleading "Running for all packages" message that would
            # immediately be overridden.  Bare -k falls through and
            # honors --all / --libraries / change detection.
            package_dirs = []
        else:
            package_dirs = _resolve_scoped_packages(args)
        elevated_packages: set[str] | None = None
        if args.elevated_packages:
            elevated_packages = {
                name.strip()
                for name in args.elevated_packages.split(",")
                if name.strip()
            } or None
        return test_cpython(
            package_dirs,
            filter_expression=args.filter_expression,
            exit_first=args.exit_first,
            verbose=args.verbose,
            no_cov=args.no_cov,
            coverage_threshold=args.coverage_threshold,
            elevated_packages=elevated_packages,
            package_workers=args.package_workers,
            quiet=args.quiet,
            slow_test_threshold_s=args.slow_test_threshold_cpython,
        )

    if args.task == "verify-examples":
        return verify_examples(_resolve_scoped_packages(args))

    if args.task == "docs":
        return docs(
            _resolve_scoped_packages(args),
            serve=args.serve,
            package_workers=args.package_workers,
            quiet=args.quiet,
        )

    if args.task == "docs-preview":
        return docs_preview(_resolve_scoped_packages(args))

    # --- tasks with specific arguments ---

    if args.task == "new-library":
        return new_library(args.name)

    if args.task == "test-scripts":
        return test_scripts(exit_first=args.exit_first, verbose=args.verbose)

    if args.task == "docs-deploy":
        library_filter = args.libraries.split(",") if args.libraries else None
        return docs_deploy(args.channel, libraries=library_filter)

    if args.task == "validate-mip":
        return validate_mip(
            bundle_repo=args.bundle_repo,
            libraries=args.libraries,
            micropython_binary=args.micropython_binary,
            staging_dir=args.staging_dir,
        )

    if args.task == "preflight":
        return preflight(
            args.micropython_binary,
            args.circuitpython_binary,
            coverage_threshold=args.coverage_threshold,
            with_functional=args.with_functional,
            with_device_unit=args.with_device_unit,
            phase_workers=args.phase_workers,
            package_workers=args.package_workers,
            quiet=args.quiet,
            slow_test_threshold_cpython=args.slow_test_threshold_cpython,
            slow_test_threshold_unix_port=args.slow_test_threshold_unix_port,
        )

    if args.task == "test-micropython":
        package_dirs = _resolve_optional_scope(args)
        return test_micropython(
            args.micropython_binary, package_dirs,
            slow_test_threshold_s=args.slow_test_threshold_unix_port,
        )

    if args.task == "test-circuitpython":
        package_dirs = _resolve_optional_scope(args)
        return test_circuitpython(
            args.circuitpython_binary, package_dirs,
            slow_test_threshold_s=args.slow_test_threshold_unix_port,
        )

    if args.task == "test-all-runtimes":
        package_dirs = _resolve_optional_scope(args)
        return test_all_runtimes(
            args.micropython_binary, args.circuitpython_binary, package_dirs,
            slow_test_threshold_s=args.slow_test_threshold_unix_port,
        )

    if args.task == "test-functional":
        return test_functional(
            verbose=args.verbose, exit_first=args.exit_first,
        )

    if args.task == "test-libraries-functional":
        return test_libraries_functional(
            runtime=args.runtime,
            micropython_device=args.micropython_device,
            circuitpython_device=args.circuitpython_device,
            library=args.library,
            file_filter=args.file_filter,
            function_filter=args.function_filter,
            deploy_mode=args.deploy_mode,
        )

    if args.task == "test-workbench-functional":
        return test_workbench_functional(
            workbench=args.workbench,
            file_filter=args.file_filter,
            function_filter=args.function_filter,
            verbose=args.verbose,
            exit_first=args.exit_first,
        )

    if args.task == "test-unit-on-device":
        return test_unit_on_device(
            runtime=args.runtime,
            micropython_device=args.micropython_device,
            circuitpython_device=args.circuitpython_device,
            deploy_mode=args.deploy_mode,
            library=args.library,
            per_file=args.per_file,
        )

    if args.task == "build":
        return build(package_workers=args.package_workers, quiet=args.quiet)

    if args.task == "check-api":
        return check_api(max_workers=args.max_workers, base=args.base)

    if args.task == "check-version":
        return check_version(base=args.base)

    # --- no-arg tasks ---
    no_arg: dict[str, Callable[[], int]] = {
        "setup": setup,
        "sync-ide": sync_ide,
        "lint": lint,
        "prepare-micropython": prepare_micropython,
        "prepare-circuitpython": prepare_circuitpython,
        "prepare-mpy-cross": prepare_mpy_cross,
        "check-dep-graph": check_dep_graph,
    }

    if args.task in no_arg:
        return no_arg[args.task]()

    # Defense in depth: argparse rejects unknown subcommands before
    # reaching here, so this branch is unreachable in normal CLI use.
    print(f"Unknown task: {args.task}")  # pragma: no cover
    return 1  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
