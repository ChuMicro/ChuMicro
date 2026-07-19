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
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# Hot-path imports, touched by lint, run_command, and ROOT-derived path
# discovery on every invocation.  Heavier imports (check_api,
# docs_deploy, prepare_*, validate_mip_install, verify_examples,
# new_library_scaffold, ide_sync, render_dep_graph,
# shared.install_workspace) are deferred into the task wrappers that
# need them.  Each of those modules pulls in tomllib, yaml, ast walkers,
# griffe, mike, and so on.  Eager-loading them meant every phase that
# subprocess-re-invokes ``python scripts/run.py`` (Decision 0048) paid
# the full import-time tax even when running a task that didn't touch
# them.
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
    is_parked,
    is_ref_reachable,
    pythonpath_environment,
    resolve_scope,
)
from shared import run_command, stream_subprocess

PYTHON = sys.executable


def _default_package_workers() -> int:
    """Return the per-package fan-out worker default sized for this host.

    Build / docs / test fan out one subprocess per package (``python -m
    build``, ``python -m zensical build``, or pytest), mostly I/O-bound
    (process spawn, file reads), so the fan-out hits its
    diminishing-returns ceiling around 8 packages wide.  Override via
    ``--package-workers``.

    The preflight *phase* count is not capped here: each phase is a
    thread streaming a subprocess, so a phase cap bounds no real
    resource — preflight runs every phase at once by default
    (Decision 0048).  Override the phase count via ``--phase-workers``.
    """
    cores = max(2, os.cpu_count() or 4)
    return max(2, min(8, cores // 2 + 2))


#: Default cap on concurrent per-package subprocesses for build /
#: docs / test fan-out.  See :func:`_default_package_workers`;
#: override via ``--package-workers``.
_DEFAULT_PACKAGE_PARALLEL_WORKERS = _default_package_workers()


#: Default slow-test threshold for host CPython tests (seconds).
#: Tests crossing this duration are surfaced as warn-only "SLOW"
#: notices in the rolled-up phase summary; see
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
#: ``CHUMICRO_RAW_OUTPUT``, which is an internal subprocess signal).
#: Useful in IDE Run-config environments where ``isatty()`` is False
#: but the user is reading the output live in an interactive console.
#: Accepted values: ``status``, ``interleave``, ``quiet``.
_OUTPUT_MODE_ENV_VAR = "CHUMICRO_OUTPUT_MODE"


# ---------------------------------------------------------------------------
# Output dispatcher: routes parallel-phase output to the user.
#
# Four modes:
#
# - ``quiet``: every line is buffered; on finish() the dispatcher
#   replays each phase's full transcript under a ``== <label> ==``
#   header in submission order.  This is the original (pre-2026-05)
#   behavior, selected only by ``--quiet`` or
#   ``CHUMICRO_OUTPUT_MODE=quiet`` — not the default for any context.
# - ``interleave``: phase events (started / done) and every line of
#   output print live, prefixed with ``[label]``.  Default for
#   non-TTY contexts (CI logs, ``run.py preflight > out.log``), which
#   is the agent / log-capture path.
# - ``status``: phase events print live (``→ lint``, ``✓ lint
#   (1.2s)``); per-line output is suppressed during the run; on
#   finish(), failed phases get a full transcript dump under a
#   ``== <label> (failed) ==`` header.  Default for TTY contexts.
# - ``raw``: used only by the child of a subprocess re-invocation
#   (when ``CHUMICRO_RAW_OUTPUT`` is set in the env).  Lines print raw
#   to stdout so the parent's pipe reader can frame them.  No phase
#   events, no headers.
#
# The dispatcher is constructed by :func:`_pick_dispatcher` based on
# CLI flag + TTY + env-var detection.
# ---------------------------------------------------------------------------


@dataclass
class _PhaseResult:
    """Outcome of one parallel phase: status, wall time, and transcript.

    Carries what the end-of-run summary table and the failure recap
    need that the live dispatcher discards — the interleave dispatcher
    prints every line and buffers nothing, so the recap pulls the
    failing phase's last lines from :attr:`captured` here instead.
    """

    label: str
    exit_code: int
    elapsed_s: float
    captured: str


class _ProcessRegistry:
    """Tracks live phase subprocesses so they can be killed on interrupt.

    :func:`_run_parallel_phases` owns one registry and passes it into
    every phase's :class:`_Sink`.  Phase callables that spawn a child
    register it; on a :class:`KeyboardInterrupt` (or any termination)
    the runner terminates each registered process *group* — the child
    started in its own session, so killing the group reaps grandchildren
    (a pytest worker, a unix-port binary) that would otherwise orphan
    and keep holding a serial port.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: list[subprocess.Popen] = []

    def add(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._processes.append(process)

    def terminate_all(self) -> None:
        """Terminate every tracked process group: SIGTERM, brief wait, SIGKILL."""
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            self._signal_group(process, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._signal_group(process, signal.SIGKILL)

    @staticmethod
    def _signal_group(process: subprocess.Popen, sig: int) -> None:
        """Signal the child's whole process group, ignoring an already-dead child."""
        if process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(process.pid), sig)
        except (ProcessLookupError, PermissionError):
            pass


class _Sink:
    """Per-phase output sink, passed into a phase callable.

    Each phase callable receives a sink and emits lines through it via
    ``sink.line(text)``.  The sink records every line into a local
    buffer (so ``sink.captured`` returns the full transcript at the
    end) *and* forwards it to the dispatcher for live routing.

    The streaming subprocess helper :func:`shared.stream_subprocess`
    accepts ``on_line=sink.line`` so phase callables can pipe child
    output through the sink with one line of glue.
    """

    __slots__ = ("_dispatcher", "_label", "_buffer", "_registry")

    def __init__(
        self,
        dispatcher: _Dispatcher,
        label: str,
        registry: _ProcessRegistry | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._label = label
        self._buffer: list[str] = []
        self._registry = registry

    def line(self, text: str) -> None:
        """Record one line and forward it to the dispatcher."""
        self._buffer.append(text)
        self._dispatcher.phase_line(self._label, text)

    def register_process(self, process: subprocess.Popen) -> None:
        """Track a live child so the runner can terminate it on interrupt.

        Phase callables that spawn a subprocess pass this as
        ``stream_subprocess(..., on_start=sink.register_process)``.  A
        no-op when the sink has no registry (standalone runs).
        """
        if self._registry is not None:
            self._registry.add(process)

    @property
    def captured(self) -> str:
        """Return the full captured transcript with a trailing newline."""
        if not self._buffer:
            return ""
        return "\n".join(self._buffer) + "\n"


class _Dispatcher:
    """Coordinates output from multiple parallel phases.

    Lifecycle: ``start(labels)``, then many ``phase_started`` /
    ``phase_line`` / ``phase_done`` calls (concurrent, from worker
    threads), then ``finish()``.  Implementations must serialize their
    own output (e.g. with a lock): phase callbacks fire from worker
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

    The original (pre-2026-05) behavior, selected by ``--quiet`` or
    ``CHUMICRO_OUTPUT_MODE=quiet`` for any consumer that wants the
    deterministic per-phase header layout.
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
            # When any phase failed, suppress passing-phase transcripts.
            # Otherwise the user has to scroll past N successful phases
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
    """Live phase events with elapsed time.  Failure logs dumped at end.

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
    in the env.  We're one phase of the parent's run.  The parent will
    read our stdout line-by-line and re-frame each line under the right
    phase header.  Emit raw lines, no phase events.
    """

    def __init__(self) -> None:
        # The child's own test_cpython fan-out drives phase_line from up
        # to package_workers worker threads.  print() issues write(text)
        # then write(end) non-atomically, so two threads can fuse their
        # halves into a torn line in the parent's captured transcript
        # (corrupting both the log and the pytest-summary parse).  Hold
        # the lock across the whole print so each line lands intact.
        self._lock = threading.Lock()

    def phase_line(self, label: str, text: str) -> None:
        with self._lock:
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
    Run console pane.  `isatty()` returns False even though the user is
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
      1. ``CHUMICRO_RAW_OUTPUT`` env var: raw (we're a child of a
         parent dispatcher, never user-set).
      2. ``--quiet`` flag: quiet.
      3. ``CHUMICRO_OUTPUT_MODE`` env var: the named dispatcher.
         Lets IDEs and CI configs pin a mode without changing the
         CLI invocation.
      4. interactive console (TTY or PyCharm Run pane): status.
      5. otherwise: interleave (non-interactive CI / log capture).
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


def verify_demos() -> int:
    """Compile-check every ``.py`` under ``demos/``."""
    from verify_demos import verify_demos as _verify
    return _verify()


def new_library(name: str, *, workbench: bool = False) -> int:
    """Scaffold a new device library (or host-only workbench tool)."""
    from new_library_scaffold import new_library as _new_library
    return _new_library(name, workbench=workbench)


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

    - **Bare** (``heartbeat``): standard pytest ``-k``.  ``package_dirs``
      is untouched; every selected library runs with this expression.
    - **Library-scoped** (``timing/test_heartbeat``): the named
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
        # Bare pytest-style filter, leave package_dirs alone.
        return package_dirs, {
            package_dir.name: [(None, filter_expression)]
            for package_dir in package_dirs
        }

    # Library-scoped: library names override package_dirs.
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

    - **Global** (no file specified): combined with ``or`` into a single
      pytest invocation across the whole ``tests/`` directory.
    - **File-scoped** (``library/file/expression``): each gets its own
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
    threshold (no ``elevated_packages`` scoping).  When it *is* scoped,
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
    allow_no_tests: bool = False,
) -> int:
    """Run the CPython test suite for the given packages.

    Runs pytest separately for each package to avoid test-directory name
    collisions (Decision 0009), then combines and reports coverage.  Each
    library must independently meet the coverage threshold unless
    *filter_expression* is set (filtering naturally reduces coverage) or *no_cov*
    skips coverage entirely.

    The default threshold comes from ``pyproject.toml`` (85 %, the human
    baseline).  Pass *coverage_threshold* to override it; agents use 94 %
    (Decision 0025).

    When *elevated_packages* is provided, only those libraries (by name)
    use *coverage_threshold*; all other libraries fall back to the
    ``pyproject.toml`` default.  This lets agents enforce a higher bar on
    the libraries they changed without failing on pre-existing coverage
    in libraries they didn't touch.

    *filter_expression* accepts two forms::

        heartbeat                             # bare pytest -k, applied to all selected libraries
        timing/test_heartbeat                 # library-scoped: by name in one library
        timing/test_ticks/ticks_add           # library-scoped: by file and name
        timing/ticks_diff,runner/task_handle  # comma-separated library-scoped entries

    Bare filters (no ``/``) match vanilla pytest's ``-k`` semantics and
    preserve whatever scope was already selected (``--all``,
    ``--libraries``, or change detection).  Library-scoped filters
    override the scope and target only the named libraries.

    When *filter_expression* is active every package's pytest exit-5
    ("no tests collected") is normalized to 0 and coverage — which would
    otherwise flag a zero-test package — is skipped, so a filter that
    matches nothing would report a silent green.  Guard against that: if
    a filter selected zero tests across every chosen package, fail with a
    clear message unless *allow_no_tests* opts out.
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
    seen_labels: set[str] = set()
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

        # A testable package whose coverage source resolves to nothing
        # would run pytest with a gate flag but no ``--cov``, so
        # pytest-cov never activates and the gate is inert (the failure
        # mode that hid pytest-device's true coverage; preflight-audit
        # 2026-06-12).  When coverage is being enforced, refuse loudly
        # rather than ship a silently-ungated package.
        if not no_cov and not coverage_args_for([package_dir]):
            print(
                f"ERROR: {package_dir.relative_to(ROOT)} has tests but no "
                f"resolvable coverage source (missing src/<pkg>/__init__.py?)."
                f"  Coverage gate would be inert; failing the test phase.",
            )
            return 1

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
            # in ``chumicro_deploy``) at session start, *before*
            # pytest-cov begins instrumenting, missing import-time
            # coverage (dataclass definitions, regex compiles) on
            # both the plugin's tree and ``chumicro_deploy.config.default``.
            # Functional-test runs (``test-libraries-functional``) load
            # the plugin via the same entry point and aren't affected
            # because they don't measure coverage of those modules.
            disable_plugin_args = ["-p", "no:chumicro_pytest_device"]

            # Unique coverage file per run keeps data attributable
            # under parallel fan-out: every concurrent pytest writes
            # to its own ``.coverage.<package>.<run>`` file before
            # ``coverage combine`` merges them.
            coverage_name = f".coverage.{package_dir.name}.{run_counter}"
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
            # Two file-scoped ``-k`` entries naming the same test file
            # produce identical labels; suffix the run index so each
            # phase keeps its own dispatcher slot and test tally.
            if label in seen_labels:
                label = f"{label}#{run_counter}"
            seen_labels.add(label)
            run_counter += 1
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

    overall_exit_code, _failing_label, _phase_results = _run_parallel_phases(
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

    # Zero-collected floor.  A ``-k`` filter that deselects everything
    # leaves each phase at exit 5 (normalized to 0) with the coverage gate
    # skipped, so nothing catches "the filter matched no tests".  Fail
    # loudly when a filter is active but no test actually ran, unless the
    # caller explicitly allows a zero-test run.
    tests_run = sum(result.passed + result.skipped for result in collector.results)
    if (
        filter_expression is not None
        and overall_exit_code == 0
        and tests_run == 0
        and not allow_no_tests
    ):
        print(
            f"ERROR: filter {filter_expression!r} selected 0 tests across the "
            "chosen packages — nothing ran.  Re-check the filter, or pass "
            "--allow-no-tests if a zero-test run is expected.",
        )
        return 1

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

    Pytest exit code 5 ("no tests collected", typically when a
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
        if filter_state.coverage_failure is not None:
            total, fail_under = filter_state.coverage_failure
            sink.line(
                f"ERROR: {phase_label} coverage {total}% < "
                f"fail-under={fail_under}%",
            )
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


#: pytest-cov's own per-run gate-failure line, emitted unlabeled to
#: stdout.  Captured so the phase can re-emit it prefixed with the
#: package label (the fan-out collapses every run's stdout into one
#: stream, so an unlabeled "total of 87 < fail-under=94" can't be
#: attributed to a package otherwise).
_PYTEST_COVERAGE_FAILURE = re.compile(
    r"Coverage failure: total of (?P<total>\d+) is less than "
    r"fail-under=(?P<fail_under>\d+)",
)


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

#: ANSI CSI escape sequences (SGR colour codes and friends).  pytest
#: colourizes its summary, ``slowest durations`` header, and coverage
#: failure line whenever it writes to a tty or sees ``FORCE_COLOR``.  A
#: coloured ``\x1b[32m=== 5 passed …\x1b[0m`` no longer starts with ``=``,
#: so the summary regexes below miss it and the parsed counts stay 0.
#: Strip these before matching (see :func:`_strip_ansi`).
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    """Return *text* with ANSI escape sequences removed.

    Shared sanitizer applied at the front of :meth:`_PytestOutputFilter.consume`
    so the summary / durations / deselected / coverage-failure regexes match
    the same whether pytest emitted plain or coloured output.  Only used for
    *parsing*; the original (possibly coloured) line still flows to the log.
    """
    return _ANSI_ESCAPE.sub("", text)


@dataclass
class _PytestRunResult:
    """Parsed summary of a single pytest invocation."""

    label: str
    exit_code: int
    passed: int = 0
    skipped: int = 0
    deselected: int = 0
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
            deselected=filter_state.deselected,
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
    Returns ``True`` from :meth:`consume` when a line was absorbed.
    The wrapping sink then suppresses forwarding to the dispatcher.

    Lines that don't match a known summary form (test progress dots,
    failure tracebacks, "+ pytest ..." command echo, etc.) pass
    through unchanged.
    """

    def __init__(self) -> None:
        self.passed = 0
        self.skipped = 0
        self.deselected = 0
        self.duration_s = 0.0
        self.slow_tests: list[tuple[float, str]] = []
        #: ``(total_percent, fail_under_percent)`` from pytest-cov's gate
        #: failure line, or ``None`` when the run met its coverage gate.
        self.coverage_failure: tuple[int, int] | None = None
        self._in_slow_block = False

    def consume(self, text: str) -> bool:
        # Strip ANSI colour first: under FORCE_COLOR / a tty pytest wraps its
        # summary and durations lines in SGR escapes, which would otherwise
        # defeat the anchored regexes below and leave every count at 0.
        stripped = _strip_ansi(text).rstrip()
        coverage_failure = _PYTEST_COVERAGE_FAILURE.search(stripped)
        if coverage_failure is not None:
            # Record the percentages and drop the unlabeled line; the
            # phase closure re-emits it prefixed with the package label.
            self.coverage_failure = (
                int(coverage_failure.group("total")),
                int(coverage_failure.group("fail_under")),
            )
            return True
        if _PYTEST_SLOW_HEADER.match(stripped):
            self._in_slow_block = True
            return True
        if self._in_slow_block:
            row = _PYTEST_SLOW_ROW.match(stripped)
            if row is not None:
                # Only count ``call`` durations.  Setup and teardown
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
            if match.group("deselected"):
                self.deselected += int(match.group("deselected"))
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

    Returns one summary line, one FAILED line per failing run, then
    optional SLOW notices.  The summary follows pytest's own ``X passed
    [, Y skipped] [, Z deselected] in Ws`` shape so log scanners that
    already grep for "passed in" keep working, prefixed with the phase
    label.  When *results* spans multiple pytest invocations (per-package
    fan-out under :func:`test_cpython`) the line gains an ``across N
    libraries`` clause; a single invocation omits it.

    Each run whose ``exit_code`` is non-zero gets its own
    ``<label>: FAILED <run-label> (exit=N)`` line so a coverage-gate or
    test failure inside the fan-out is attributable to the package that
    produced it — the rolled-up "N passed" line alone reads as a clean
    pass even on a phase that exited 1.

    Deselected counts surface a ``-k`` filter or marker exclusion that
    silently removed test files from the run; without this the count is
    parsed and dropped.

    Slow notices list every test whose ``call`` duration crossed
    *slow_threshold_s*.  Warn-only: the caller's exit code is
    unaffected.
    """
    passed = sum(result.passed for result in results)
    skipped = sum(result.skipped for result in results)
    deselected = sum(result.deselected for result in results)
    duration_s = sum(result.duration_s for result in results)

    pieces = [f"{passed} passed"]
    if skipped:
        pieces.append(f"{skipped} skipped")
    if deselected:
        pieces.append(f"{deselected} deselected")
    summary = f"{label}: {', '.join(pieces)}"
    if len(results) > 1:
        summary += f" across {len(results)} libraries"
    summary += f" in {duration_s:.2f}s"
    lines = [summary]
    for result in results:
        if result.exit_code != 0:
            lines.append(
                f"{label}: FAILED {result.label} (exit={result.exit_code})",
            )
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
    """Run pytest on scripts/tests/, the infrastructure test suite.

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

    Builds are fanned out across *package_workers* threads.  Each
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
    result, _failing_label, _phase_results = _run_parallel_phases(
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
    exit_code, _failing_label, _phase_results = _run_parallel_phases(
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
    sees output the moment zensical emits it, with no buffer-and-replay
    delay even on slow library builds.
    """
    def build_one(sink: _Sink) -> int:
        relative_path = library_dir.relative_to(ROOT)
        site_dir = library_dir / "site"
        # mkdocstrings + griffe cache parsed-AST results in
        # ``<library>/.cache/``.  When cached entries are reused, griffe
        # does not re-emit warnings on stdout, and the warning-scan
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
    # commits to the same ``_docs-preview`` git branch.  Running them
    # concurrently would race on the git index lock.  Unlike ``docs``
    # (which fans out per library because each writes to its own
    # ``site/`` directory), the ``mike`` workflow serializes onto one
    # git index.  Worktree-per-library would let us parallelize, but
    # the wall time of an interactive ``docs-preview`` is dominated by
    # ``mike serve`` afterwards, so the speedup wouldn't be visible to
    # the user.
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


#: Number of trailing transcript lines the failure recap re-prints.
_FAILURE_RECAP_LINES = 40


def _format_preflight_phase_table(
    parallel_specs: Sequence[tuple[str, list[str] | None]],
    phase_results: Sequence[_PhaseResult],
) -> list[str]:
    """Build the per-phase status table in submission order.

    One row per spec: label, ``PASS`` / ``FAIL`` / ``SKIP``, and wall
    seconds.  A spec whose args are ``None`` was skipped (origin/main
    unreachable) and has no :class:`_PhaseResult`; everything else maps
    by label to its result.  Submission order matches the spec list so
    the table reads "lint first, test-circuitpython last" regardless of
    finish order.
    """
    by_label = {result.label: result for result in phase_results}
    label_width = max((len(label) for label, _ in parallel_specs), default=0)
    lines = ["", "Phase summary:"]
    for label, args in parallel_specs:
        if args is None:
            lines.append(f"  {label:<{label_width}}  SKIP")
            continue
        result = by_label.get(label)
        if result is None:
            # Phase never recorded a result (cancelled mid-interrupt).
            lines.append(f"  {label:<{label_width}}  ----")
            continue
        status = "PASS" if result.exit_code == 0 else "FAIL"
        lines.append(
            f"  {label:<{label_width}}  {status}  {result.elapsed_s:6.1f}s",
        )
    return lines


def _format_preflight_failure_recap(
    failing_label: str | None,
    phase_results: Sequence[_PhaseResult],
) -> list[str]:
    """Re-print the failing phase's last lines under a clear header.

    The live interleave stream leaves the root cause hundreds of lines
    above EOF (every later-finishing phase's output piles on top).  This
    pulls the failing phase's last :data:`_FAILURE_RECAP_LINES` captured
    lines back to the tail so a log reader lands on the error.
    """
    if failing_label is None:
        return []
    result = next(
        (phase for phase in phase_results if phase.label == failing_label),
        None,
    )
    if result is None or not result.captured:
        return []
    tail = result.captured.splitlines()[-_FAILURE_RECAP_LINES:]
    return [
        "",
        f"== {failing_label} (failed) — last {len(tail)} lines ==",
        *tail,
    ]


def preflight(
    micropython_binary: str | None = None,
    circuitpython_binary: str | None = None,
    coverage_threshold: int | None = None,
    with_functional: bool = False,
    with_device_unit: bool = False,
    phase_workers: int | None = None,
    package_workers: int = _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    quiet: bool = False,
    slow_test_threshold_cpython: float = _DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
    slow_test_threshold_unix_port: float = _DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
) -> int:
    """Run the full check suite that CI requires on every pull request.

    Mirrors the CI matrix as closely as possible on the local machine:
    lint, build, docs (with griffe warning detection), CPython tests,
    scripts infrastructure tests, example verification, size-budget
    check, version-check, api-check, MicroPython and CircuitPython
    cross-runtime unit tests.

    The 13 phases run **in parallel** as independent subprocess
    re-invocations of ``python scripts/run.py <subcommand>`` (two of the
    13 — check-version and check-api — skip when ``origin/main`` is
    unreachable).  See Decision 0048 for the design.  Output routing
    depends on the context (Decision 0054): a TTY gets the status
    dispatcher (per-phase events live, failing-phase transcript dumped
    at the end); ``--quiet`` / ``CHUMICRO_OUTPUT_MODE=quiet`` buffers
    and replays each phase under a ``== <label> ==`` header in
    submission order; a redirected / non-TTY stdout (CI, ``preflight >
    out.log``) gets live ``[label]``-prefixed interleave.  After the
    parallel block, every mode prints a per-phase status table and, on
    failure, a recap of the failing phase's last lines so the root
    cause sits at the tail.  The ``--with-functional`` tail stays serial
    because both phases drive the same physical hardware.

    Pass *coverage_threshold* to override the ``pyproject.toml`` default
    (85 %).  Agents should pass ``--coverage-threshold 94`` (Decision 0025).

    Tests run once with the current Python interpreter (CI runs 3.11,
    3.12, and 3.13 separately).  Version-check and api-check require
    ``origin/main`` to be reachable; they skip gracefully if it is not.

    Functional tests on real hardware are skipped by default: they
    require a connected board.  Pass *with_functional* to append
    ``test-libraries-functional`` and ``test-workbench-functional``
    (running with ``devices.yml`` defaults) to the end of the sweep.
    Pass *with_device_unit* to also append ``test-unit-on-device``
    (the cross-runtime unit suite on connected boards) after that,
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
        # packages are considered "changed".  Leave elevated_package_names
        # as None so the threshold applies everywhere.

    # version-check and api-check need a base ref to diff against.
    # If origin/main isn't reachable (detached HEAD, no remote, etc.),
    # skip them with a warning rather than crashing preflight.  We
    # decide reachability here in the parent so the parallel block
    # never sees an unreachable phase.  The skip line prints in the
    # per-phase ordering below.
    base_reference = "origin/main"
    can_diff = is_ref_reachable(base_reference)

    # Build the parallel-phase list.  Order matters for the per-phase
    # status table and the quiet-mode replay, both of which render in
    # submission order, so the log keeps the documented "lint first,
    # test-circuitpython last" shape regardless of which phase finishes
    # first.
    # Forward --package-workers to subcommands whose internal fan-out
    # honors the cap (test, build, docs, check-api).  Phases that don't
    # fan out per-package (lint, test-scripts, verify-examples,
    # check-dep-graph, check-size, check-version, test-micropython,
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
        ("verify-demos", ["verify-demos"]),
        ("check-dep-graph", ["check-dep-graph"]),
        ("check-size", ["check-size"]),
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
            (label, _subcommand_phase_factory(label, args)),
        )

    # Print skip notices up-front so the user sees them before the
    # parallel block.  Order: same as in the spec list above.
    for label in skipped_phases:
        print(f"== {label} ==")
        print(f"  SKIP: {base_reference} not reachable (fetch or set --base).")

    dispatcher = _pick_dispatcher(quiet=quiet)
    parallel_result, failing_label, phase_results = _preflight_run_parallel_phases(
        parallel_phases,
        max_workers=phase_workers,
        dispatcher=dispatcher,
    )

    # Print a per-phase status table in submission order so the run's
    # shape is legible at a glance regardless of which dispatcher routed
    # the live stream.  On failure, follow it with a recap of the
    # failing phase's last lines so the root cause sits at EOF instead
    # of buried hundreds of interleaved lines above.
    for line in _format_preflight_phase_table(
        parallel_specs, phase_results,
    ):
        print(line)

    if parallel_result != 0:
        for line in _format_preflight_failure_recap(failing_label, phase_results):
            print(line)
        # Final labeled banner so the failing phase survives
        # interleaved-output schedulers where its [FAIL] line scrolls
        # past the visible tail.
        if failing_label is not None:
            print(f"Preflight failed at: {failing_label}")
        else:
            print("Preflight failed.")  # pragma: no cover - defensive
        return parallel_result

    # Functional tests on real hardware run **after** the parallel
    # block and **serially** between themselves: both phases drive
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
    # serially here too, after functional, never concurrently.
    if with_device_unit:
        print("== test-unit-on-device ==")
        result = test_unit_on_device()
        if result != 0:
            print("Preflight failed at: test-unit-on-device")
            return result

    total_tests = _tally_pytest_counts(dispatcher.captured_outputs())
    if total_tests > 0:
        print(
            f"Preflight passed.  Required CI checks should pass.  "
            f"{total_tests} tests ran across all phases.",
        )
    else:
        print("Preflight passed.  Required CI checks should pass.")
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


def _run_parallel_phases(
    phases: Sequence[tuple[str, Callable[[_Sink], int]]],
    *,
    dispatcher: _Dispatcher,
    max_workers: int | None = None,
) -> tuple[int, str | None, list[_PhaseResult]]:
    """Run *phases* concurrently, routing output through *dispatcher*.

    Each phase callable receives a per-phase :class:`_Sink`.  The sink
    forwards every line to the dispatcher (which decides what to do
    with it: buffer, prefix-and-print, or render in a status block)
    and also accumulates the full transcript on the sink object so the
    runner can hand it back to the dispatcher on phase completion.

    The dispatcher's lifecycle methods (``start`` / ``phase_started``
    / ``phase_done`` / ``finish``) are invoked from worker threads.
    Implementations are expected to serialize their own output with a
    lock.

    Args:
        phases: ``(label, callable)`` pairs.  Each callable takes a
            :class:`_Sink` and returns the phase's exit code.
        dispatcher: Routes phase events + lines to the user.
        max_workers: Cap on concurrent phases.  ``None`` (default) is
            ``len(phases)``, so every phase runs at once.  Pass an
            integer to throttle for CPU / subprocess oversubscription.

    Returns:
        ``(exit_code, failing_label, phase_results)``: first non-zero
        exit code in submission order paired with its phase label (or
        ``(0, None, …)`` when every phase succeeded), plus a
        :class:`_PhaseResult` per phase in submission order.  The label
        lets callers print ``Preflight failed at: <label>`` summaries
        that survive interleaved-output schedulers where the failing
        phase's ``[FAIL]`` line scrolls past the visible tail; the
        results carry per-phase wall time and transcript for the
        end-of-run table and failure recap.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    if not phases:
        return 0, None, []

    labels = [label for label, _ in phases]
    # Every dispatcher keys its per-phase state by label (the quiet and
    # status dispatchers store results in a dict).  A duplicate label
    # silently overwrites one phase's transcript with another's and
    # drops it from the test tally, so reject collisions up front.  A
    # user-reachable form is two file-scoped ``-k`` entries naming the
    # same test file.
    duplicate_labels = sorted({
        label for label in labels if labels.count(label) > 1
    })
    if duplicate_labels:
        raise ValueError(
            f"Duplicate phase label(s): {', '.join(duplicate_labels)}.  "
            f"Phase labels must be unique.",
        )
    dispatcher.start(labels)

    registry = _ProcessRegistry()
    results_by_label: dict[str, _PhaseResult] = {}
    results_lock = threading.Lock()

    def run_one(label: str, work: Callable[[_Sink], int]) -> tuple[str, int]:
        sink = _Sink(dispatcher, label, registry)
        dispatcher.phase_started(label)
        start = time.monotonic()
        try:
            exit_code = work(sink)
        except Exception as error:  # pragma: no cover - defensive
            sink.line(f"Phase {label!r} crashed: {error}")
            exit_code = 1
        elapsed = time.monotonic() - start
        dispatcher.phase_done(label, exit_code, sink.captured)
        with results_lock:
            results_by_label[label] = _PhaseResult(
                label, exit_code, elapsed, sink.captured,
            )
        return label, exit_code

    workers = max_workers if max_workers is not None else len(phases)
    workers = max(1, min(workers, len(phases)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(run_one, label, work) for label, work in phases
        ]
        try:
            results = [future.result() for future in futures]
        except KeyboardInterrupt:
            # Stop launching queued phases and reap every live child's
            # process group so a pytest worker can't orphan and keep a
            # serial port locked.  cancel_futures drops not-yet-started
            # work; terminate_all signals the running groups.
            executor.shutdown(wait=False, cancel_futures=True)
            registry.terminate_all()
            raise

    dispatcher.finish()

    phase_results = [
        results_by_label[label] for label in labels if label in results_by_label
    ]
    for label, exit_code in results:
        if exit_code != 0:
            return exit_code, label, phase_results
    return 0, None, phase_results


def _subcommand_phase_factory(
    label: str,
    subcommand_args: list[str],
) -> Callable[[_Sink], int]:
    """Build a phase that subprocess-runs ``python scripts/run.py <args>``.

    The child runs with ``CHUMICRO_RAW_OUTPUT=1`` in its environment so
    its own dispatcher resolves to :class:`_RawDispatcher`.  The child
    prints raw lines to its stdout, and our ``stream_subprocess`` reads
    them line-by-line and routes them through this phase's sink, where
    the parent's dispatcher decides how to render them (buffer, prefix,
    status-line).

    Subprocess re-invocation (rather than an in-process call) keeps
    each phase's resource footprint isolated and lets us cleanly
    capture *all* of the phase's output at the fd level.  The
    in-process alternative would have to thread sinks through every
    helper that prints.

    Args:
        label: Phase header (used in failure banners).
        subcommand_args: Arguments to append after ``[python,
            "scripts/run.py"]``, e.g. ``["lint"]`` or ``["test",
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
    total reflects all tests actually executed: host CPython plus
    MicroPython unix-port plus CircuitPython unix-port.

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
    max_workers: int | None = None,
    dispatcher: _Dispatcher | None = None,
) -> tuple[int, str | None, list[_PhaseResult]]:
    """Dispatch the parallel preflight phase block.

    Thin wrapper over :func:`_run_parallel_phases` that exists as a
    named seam so tests can monkeypatch the parallel block without
    forking the subprocess invocations on every preflight test.

    Returns ``(exit_code, failing_label, phase_results)`` straight
    through from the underlying runner.
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
    defaults.  For narrower runs, call the individual commands directly.
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
    caching, and the PR-summary block.  The IDE play-button path
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
        The pytest exit code: ``0`` on all-pass, ``1`` on failures,
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


#: Console marker a wifi demo prints once its first association lands
#: (``WIFI_OK ip=...``).  A freshly-erased ESP32-family board runs RF
#: calibration on its very first wifi association, which can push that
#: one join past the demo driver's WIFI_OK budget; the radio is warm on
#: the immediately-following attempt.  The sweep keys its single
#: first-association retry on a timeout waiting for THIS marker — cold
#: start is a property of the ESP32 family generally, not of any one
#: board or vendor, so no board-quirk table is involved.
_FIRST_ASSOCIATION_MARKER = "WIFI_OK"


def _demo_output_shows_first_association_timeout(output: str) -> bool:
    """True when *output* shows the demo timed out awaiting first association.

    The wifi demo drivers wait on the board's ``WIFI_OK`` marker with a
    fixed budget; a miss raises ``MarkerTimeoutError`` whose message the
    driver prints as ``... waiting for marker 'WIFI_OK'``.  That
    signature is the only cold-start candidate the sweep grants a retry
    — a *later* marker timing out (e.g. ``DEMO_COMPLETE``) is a genuine
    failure and is not retried, so the "cold-start grace" the summary
    reports stays honest.
    """
    return f"waiting for marker '{_FIRST_ASSOCIATION_MARKER}'" in output


def _run_demo_cell(driver: Path, device_id: str) -> tuple[str, str | None]:
    """Run one demo driver against *device_id*, granting one cold-start retry.

    Returns ``(cell, note)``.  ``cell`` is ``"PASS"``, ``"FAIL"``, or
    ``"PASS*"`` (passed only on the cold-start retry); ``note`` is a
    one-line summary footnote when a retry was granted, else ``None``.

    A first attempt that fails specifically on the first-association
    marker timeout (see
    :func:`_demo_output_shows_first_association_timeout`) is retried
    exactly once — the documented "run the sweep twice" bench remedy for
    ESP32-family cold-start RF calibration, automated.  Any other
    failure, and any second failure, is a plain ``FAIL``.  The retry is
    never silent: it announces itself before re-running and is called
    out under the summary table (no-silent-caps).
    """
    command = [PYTHON, str(driver), "--device", device_id]
    environment = pythonpath_environment()
    print(f"+ {' '.join(command)}", flush=True)
    code, output = stream_subprocess(
        command,
        environment=environment,
        on_line=lambda line: print(line, flush=True),
    )
    if code == 0:
        return "PASS", None
    if not _demo_output_shows_first_association_timeout(output):
        return "FAIL", None

    print(
        f"== sweep {device_id} :: demo first-association grace — "
        f"{_FIRST_ASSOCIATION_MARKER} marker timed out on a cold start; "
        f"retrying once against the now-warm radio ==",
        flush=True,
    )
    print(f"+ {' '.join(command)}", flush=True)
    retry_code, _ = stream_subprocess(
        command,
        environment=environment,
        on_line=lambda line: print(line, flush=True),
    )
    if retry_code == 0:
        return "PASS*", f"{device_id}: demo passed on retry (cold-start grace)"
    return "FAIL", (
        f"{device_id}: demo retried once on cold-start grace, still FAIL"
    )


def sweep_devices(
    *,
    device_ids: list[str] | None = None,
    demo: str = "sockets_runner_connector",
    skip_demo: bool = False,
    functional: bool = False,
    skip_workbench: bool = False,
    library: str | None = None,
    deploy_mode: str | None = None,
) -> int:
    """Run the bench-board sweep across every registered device.

    Formalizes the previously ad-hoc four-board pass: for each device
    in ``devices.yml`` (registry order), deploy and run a demo as the
    smoke layer, plus that board's library functional suite when
    ``functional`` is set.  Boards run strictly serially — the bench
    shares serial ports and host-side demo endpoints, so concurrent
    access deadlocks (Decision 0048).  Adding a board to the sweep is
    a ``devices.yml`` entry, not a code change.

    After every per-board cell completes, unless ``skip_workbench`` is
    set, the sweep closes with the workbench functional suites
    (``test_workbench_functional``) against the ``devices.yml`` default
    boards.  That host-side suite is not per-board and had no routine
    caller; folding it into the sweep keeps it from rotting.  It runs
    last so it never contends with the per-board cells for the boards.

    Args:
        device_ids: Limit the sweep to these device IDs (registry
            order is replaced by the given order).  ``None`` sweeps
            every registered device.
        demo: Demo directory name under ``demos/`` whose ``driver.py``
            is the smoke layer.
        skip_demo: Skip the demo layer (requires ``functional`` or the
            workbench phase).
        functional: Also run each board's library functional suite.
        skip_workbench: Skip the closing workbench functional suites.
        library: Limit the functional layer to one library.
        deploy_mode: Deploy-mode override for the functional layer.

    Returns:
        ``0`` when every cell passes, ``1`` on any failure, ``2`` for
        configuration problems (bad device ID, unknown demo, nothing
        to run).
    """
    from chumicro_deploy.config.default import (  # noqa: PLC0415 - deferred heavy import
        DeviceConfigError,
        load_device_registry,
    )

    run_demo = not skip_demo
    if not run_demo and not functional and skip_workbench:
        print(
            "sweep-devices: --skip-demo with --skip-workbench and no "
            "--functional leaves nothing to run."
        )
        return 2

    try:
        devices, _ = load_device_registry(workspace_root=ROOT)
    except DeviceConfigError as error:
        print(f"sweep-devices: {error}")
        return 2

    if device_ids:
        by_id = {entry.identifier: entry for entry in devices}
        unknown = [device_id for device_id in device_ids if device_id not in by_id]
        if unknown:
            print(
                f"sweep-devices: unknown device id(s): {', '.join(unknown)} "
                f"(registered: {', '.join(sorted(by_id))})"
            )
            return 2
        devices = [by_id[device_id] for device_id in device_ids]

    if not devices:
        print("sweep-devices: no devices registered in devices.yml.")
        return 2

    driver = ROOT / "demos" / demo / "driver.py"
    if run_demo and not driver.is_file():
        available = sorted(
            path.parent.name for path in (ROOT / "demos").glob("*/driver.py")
        )
        print(
            f"sweep-devices: no demo named {demo!r} "
            f"(available: {', '.join(available)})"
        )
        return 2

    failed = False
    rows: list[tuple[str, str, str, str, float]] = []
    cold_start_notes: list[str] = []
    for entry in devices:
        demo_cell = "-"
        functional_cell = "-"
        started = time.monotonic()
        # flush=True on the cell headers: with stdout redirected to a
        # file the parent's prints are block-buffered while the child
        # writes the inherited fd directly, so an unflushed header
        # would land *after* the child output it introduces.
        if run_demo:
            print(f"== sweep {entry.identifier} :: demo {demo} ==", flush=True)
            demo_cell, cold_start_note = _run_demo_cell(driver, entry.identifier)
            failed = failed or demo_cell == "FAIL"
            if cold_start_note is not None:
                cold_start_notes.append(cold_start_note)
        if functional:
            print(f"== sweep {entry.identifier} :: functional ==", flush=True)
            device_kwargs = {f"{entry.runtime}_device": entry.identifier}
            code = test_libraries_functional(
                runtime=entry.runtime,
                library=library,
                deploy_mode=deploy_mode,
                **device_kwargs,
            )
            functional_cell = "PASS" if code == 0 else "FAIL"
            failed = failed or code != 0
        rows.append((
            entry.identifier,
            entry.runtime,
            demo_cell,
            functional_cell,
            time.monotonic() - started,
        ))

    if not skip_workbench:
        # Runs only after every per-board cell above: the workbench
        # suites drive the same boards, so strict serial discipline
        # keeps them from contending for the shared serial ports.
        # flush=True for the same block-buffering reason as the cell
        # headers above — the header must precede the child output.
        print(
            "== sweep workbench-functional (devices.yml defaults) ==",
            flush=True,
        )
        started = time.monotonic()
        code = test_workbench_functional()
        rows.append((
            "workbench-functional",
            "defaults",
            "-",
            "PASS" if code == 0 else "FAIL",
            time.monotonic() - started,
        ))
        failed = failed or code != 0

    print("== sweep summary ==")
    width = max(len("device"), *(len(identifier) for identifier, *_ in rows))
    print(f"{'device':<{width}}  {'runtime':<13} {'demo':<5} {'functional':<10} elapsed")
    for identifier, runtime, demo_cell, functional_cell, elapsed in rows:
        print(
            f"{identifier:<{width}}  {runtime:<13} {demo_cell:<5} "
            f"{functional_cell:<10} {elapsed:.0f}s"
        )
    # A ``PASS*`` cell above means the demo timed out on its first
    # association and passed on the automatic retry; spell that out so
    # the grace is never a silent cap on the reported result.
    for note in cold_start_notes:
        print(f"* {note}")
    return 1 if failed else 0


def _library_has_cross_runtime_unit_suite(library_dir: Path) -> bool:
    """True when ``library_dir/tests`` holds a device-unit-eligible file.

    A file is eligible for the on-device sweep when its in-file
    markers put it in the device lane: not CPython-only
    (``__chumicro_runtimes__ = ("cpython",)``) and not host-only
    (``__chumicro_host_only__ = True``).  The lane is read via the
    shared ``chumicro_deploy`` marker predicate, the same one the
    pytest-device collector uses, so this orchestration pre-filter
    and the collector never disagree (no duplicated filename rule).
    """
    from chumicro_deploy import (  # noqa: PLC0415 - deferred heavy import
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
            # CPython-only (no device runtime in the marker), not swept.
            continue
        return True
    return False


def _library_pip_name(library_dir: Path) -> str:
    """Return the library's ``[project].name`` (the requires_flash key).

    Falls back to the ``chumicro-<dir>`` convention if the pyproject is
    unreadable.  Only used to decide whether the resolution unit is
    itself in the flagged set, so the convention is a safe default.
    """
    import tomllib  # noqa: PLC0415 - deferred; this task is rarely run

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
    transitive ``requires_flash`` closure, then groups libraries by
    resolved mode and runs each group as one single-mode
    ``--target device-unit`` pytest session per runtime.  A light
    library stays in the fast RAM session.  A ``requires_flash`` or
    data-file library lands in a flash session, where only that
    library's suite switches, not the whole sweep.

    The sweep's last-resort mode preference is **RAM** (its purpose is
    RAM-capable on-device validation; Decision 0047's flash-default
    footgun does not apply to a deliberate dev sweep).  ``--deploy-mode``
    overrides that preference.  Unlike the functional path the sweep
    does not inherit ``devices.yml``'s ``deploy_mode`` (that is tuned
    for app-shaped functional deploys).  Behavioral pass/fail only,
    no coverage gating (``coverage.py`` cannot trace MP / CP bytecode).

    Args:
        runtime: ``micropython`` / ``circuitpython`` / ``both``
            (default: both).
        micropython_device: Override the MicroPython target device ID.
        circuitpython_device: Override the CircuitPython target ID.
        deploy_mode: Override the RAM preference for every library
            (``ram`` / ``flash``).  The per-library rule still applies.
        library: Limit the sweep to one library's unit suite.
        per_file: Soft-reset before each test *file* (not just each
            library) in flash/copy sessions, so a large class-organized
            module runs on a fresh interpreter.  Opt-in, slower, for
            large suites on a 256 KB board.  No-op for RAM sessions
            (they already reset per file).

    Returns:
        ``0`` all-pass, ``1`` test failures, ``2`` configuration
        problems.  Cleanly returns ``0`` when no board is configured
        for a target runtime (matches the functional path).
    """
    from chumicro_deploy import (  # noqa: PLC0415 - deferred heavy import
        DeviceCaps,
        DeviceConfigError,
        find_libraries_requiring_flash,
        load_device_registry,
        resolve_deploy_mode,
    )
    from chumicro_workspace.device_orchestration import (  # noqa: PLC0415
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
    public ``chumicro_deploy`` API (or each workbench's own entrypoint).
    No test-harness plugin routes these, since workbench code is
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

    # Unlike host-only ``test``, this task does not pass ``-W error``.
    # Hardware-interacting tests routinely surface warnings from
    # upstream libraries (mpremote's mount/unmount leaves a file
    # finalizer, pyserial's cleanup) that are out of our control.
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
        # Auto-discover publishable libraries.  Parked libraries
        # (Decision 0107) are excluded — they are not staged into the
        # bundle, so there is nothing to validate a mip install against.
        library_names = [
            package_dir.name
            for package_dir in discover_library_dirs()
            if not is_parked(package_dir)
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


def check_size() -> int:
    """Fail when a device library outgrows its committed size budget.

    Measures each library's stripped-source and mpy-cross byte
    footprint and compares against the per-library ceilings in
    ``size-budgets.toml``.  Host-only, hermetic (no boards, no network),
    and fast.  FAILs — never skips — when the prepared mpy-cross is
    missing (with the ``prepare-mpy-cross`` remedy).  See
    ``scripts/check_size.py``.
    """
    from check_size import main as check_size_main
    return check_size_main([])


# ---------------------------------------------------------------------------
# Perf / heap benchmarking (opt-in local gate; see
# plans/workstreams/perf-benchmarking.md).  Not wired into preflight: it
# re-invokes both unix-port binaries and is a regression gate developers
# run deliberately, or a future scheduled-CI lane calls.
# ---------------------------------------------------------------------------

#: Worker the bench subcommand runs under each unix-port binary, and the
#: committed per-runtime baseline it compares against.
_BENCH_WORKER = "scripts/benches/run_bench.py"
_BENCH_BASELINE = ROOT / "scripts" / "benches" / "baseline.toml"
#: Runtimes the bench sweeps — both unix ports, same set the test lanes
#: cover.
_BENCH_RUNTIMES = ("micropython", "circuitpython")


def _bench_throughput_suffix(result: object) -> str:
    """Return a ``  <n> MB/s`` suffix for a payload bench, else ``""``."""
    payload_bytes = getattr(result, "payload_bytes", 0)
    cpu_us = getattr(result, "cpu_us", 0.0)
    if payload_bytes and cpu_us > 0:
        megabytes_per_s = payload_bytes / (cpu_us / 1e6) / 1e6
        return f"  {megabytes_per_s:.1f} MB/s"
    return ""


def _print_bench_findings(runtime: str, findings: list) -> None:
    """Render one runtime's comparison verdicts as an aligned table."""
    print(f"== bench: {runtime} ==")
    for finding in findings:
        status = finding.status.upper()
        result = finding.measured
        if result is None:
            # MISSING: in the baseline, not measured this run.
            print(
                f"  [{status:<10}] {finding.bench_id:<24} "
                f"(baseline heap {finding.baseline_heap}, "
                f"cpu {finding.baseline_cpu})",
            )
            continue
        heap_cell = f"heap {result.heap_churn_bytes:8.1f} B"
        cpu_cell = f"cpu {result.cpu_us:8.2f} us"
        if finding.baseline_heap is not None:
            heap_cell += f" (base {finding.baseline_heap:.1f})"
            ratio = result.cpu_us / finding.baseline_cpu if finding.baseline_cpu else 0.0
            cpu_cell += f" (base {finding.baseline_cpu:.2f}, x{ratio:.2f})"
        print(
            f"  [{status:<10}] {finding.bench_id:<24} {heap_cell}  "
            f"{cpu_cell}{_bench_throughput_suffix(result)}",
        )
        for reason in finding.reasons:
            if finding.is_regression:
                print(f"       -> {reason}")


def bench(
    micropython_binary: str | None = None,
    circuitpython_binary: str | None = None,
    *,
    update_baseline: bool = False,
) -> int:
    """Run every bench on both unix ports; compare against the baseline.

    Sweeps ``scripts/benches/bench_*.py`` (heap churn + CPU wall-time per
    op) under the MicroPython and CircuitPython unix-port binaries, then
    either compares the numbers against the committed
    ``scripts/benches/baseline.toml`` (default — the regression gate) or
    rewrites that file (*update_baseline*).

    Heap churn is gated exact-or-better plus a small slack; CPU is gated
    with a wide multiplicative band since laptop wall-time is noisy (see
    ``scripts/bench_baseline.py`` for the exact tolerances).  Returns 0
    when every metric is within tolerance on both runtimes, 1 on any
    regression, a worker crash, or a missing baseline.
    """
    from bench_baseline import (
        BenchOutputError,
        compare_runtime,
        parse_bench_output,
        serialize_baseline,
    )
    from prepare_circuitpython import prepare_circuitpython
    from prepare_micropython import prepare_micropython
    from shared import (
        resolve_circuitpython_binary,
        resolve_micropython_binary,
    )

    resolvers = {
        "micropython": (
            micropython_binary, resolve_micropython_binary, prepare_micropython,
        ),
        "circuitpython": (
            circuitpython_binary, resolve_circuitpython_binary,
            prepare_circuitpython,
        ),
    }

    measured_by_runtime: dict[str, dict] = {}
    for runtime in _BENCH_RUNTIMES:
        override, resolve, prepare = resolvers[runtime]
        prep_result = _ensure_unix_port_binary(
            runtime, override, lambda resolve=resolve, override=override: resolve(override),
            prepare, None,
        )
        if prep_result != 0:
            return prep_result
        binary = override or resolve(override)
        print(f"-> benching {runtime}: {binary}")
        exit_code, captured = stream_subprocess(
            [binary, _BENCH_WORKER], cwd=ROOT,
        )
        try:
            measured = parse_bench_output(captured)
        except BenchOutputError as error:
            print(f"bench worker failed on {runtime}: {error}")
            print(captured)
            return 1
        if not measured:
            print(
                f"bench worker on {runtime} produced no results "
                f"(exit {exit_code}).",
            )
            print(captured)
            return 1
        measured_by_runtime[runtime] = measured

    if update_baseline:
        from datetime import date
        text = serialize_baseline(measured_by_runtime, date.today().isoformat())
        _BENCH_BASELINE.write_text(text)
        print(f"Wrote baseline: {_BENCH_BASELINE.relative_to(ROOT)}")
        for runtime in _BENCH_RUNTIMES:
            findings = compare_runtime(measured_by_runtime[runtime], {})
            _print_bench_findings(runtime, findings)
        return 0

    if not _BENCH_BASELINE.exists():
        print(
            f"No baseline at {_BENCH_BASELINE.relative_to(ROOT)}.  "
            f"Record one with: python scripts/run.py bench --update-baseline",
        )
        return 1

    from repo_layout import load_tomllib
    baseline_doc = load_tomllib().loads(_BENCH_BASELINE.read_text())

    regressed = False
    for runtime in _BENCH_RUNTIMES:
        findings = compare_runtime(
            measured_by_runtime[runtime], baseline_doc.get(runtime, {}),
        )
        _print_bench_findings(runtime, findings)
        if any(finding.is_regression for finding in findings):
            regressed = True

    if regressed:
        print(
            "\nbench: REGRESSION — a metric crossed its tolerance band.  "
            "If the change is intended, re-record with: "
            "python scripts/run.py bench --update-baseline",
        )
        return 1
    print("\nbench: OK — every metric within tolerance on both runtimes.")
    return 0


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
    # add-device``.  Keeps the mono-repo's ``run.py`` as the single
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
        default=None,
        help=(
            "cap on concurrent preflight phases "
            "(default: run every phase at once — the cap controls no real "
            "resource since each phase is a thread streaming a subprocess)"
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
        help="deploy mode: flash (default, persistent) or ram (no flash wear). "
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

    sweep_devices_parser = subparsers.add_parser(
        "sweep-devices",
        description=(
            "Run the bench-board sweep across every device registered in "
            "devices.yml, in sequence: a demo deploy+run as the smoke "
            "layer, plus each board's library functional suite with "
            "--functional.  Formalizes the routine multi-board bench pass."
        ),
        help=(
            "run the demo smoke sweep (+ optional functional suite) on "
            "every board in devices.yml"
        ),
    )
    sweep_devices_parser.add_argument(
        "--device",
        action="append",
        dest="device_ids",
        metavar="DEVICE_ID",
        help="limit the sweep to this device id (repeatable)",
    )
    sweep_devices_parser.add_argument(
        "--demo",
        default="sockets_runner_connector",
        help=(
            "demo under demos/ whose driver.py is the smoke layer "
            "(default: sockets_runner_connector)"
        ),
    )
    sweep_devices_parser.add_argument(
        "--skip-demo",
        action="store_true",
        help="skip the demo smoke layer (requires --functional)",
    )
    sweep_devices_parser.add_argument(
        "--functional",
        action="store_true",
        help="also run each board's library functional suite",
    )
    sweep_devices_parser.add_argument(
        "--skip-workbench",
        action="store_true",
        help=(
            "skip the workbench functional suites (deploy/repl/workspace) "
            "that close the sweep"
        ),
    )
    sweep_devices_parser.add_argument(
        "--library",
        help="limit the functional layer to one library",
    )
    sweep_devices_parser.add_argument(
        "--deploy-mode",
        dest="deploy_mode",
        choices=["ram", "flash"],
        default=None,
        help="deploy-mode override for the functional layer",
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
    subparsers.add_parser(
        "check-size",
        help="fail when a device library outgrows its size-budgets.toml ceiling",
    )

    bench_parser = subparsers.add_parser(
        "bench", parents=[binary],
        help=(
            "run perf/heap benches on both unix ports and compare against "
            "the committed baseline (opt-in local gate; not in preflight)"
        ),
    )
    bench_parser.add_argument(
        "--update-baseline", action="store_true",
        help="rewrite scripts/benches/baseline.toml from this run instead of comparing",
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
        "--allow-no-tests", action="store_true",
        help=(
            "allow a filtered run to select zero tests without failing "
            "(default: a -k filter that matches nothing is an error)"
        ),
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
    subparsers.add_parser("verify-demos", help="compile-check the demos/ tree")

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
    new_library_parser.add_argument(
        "--workbench",
        action="store_true",
        help="scaffold a host-only workbench tool under workbench/ "
        "instead of a device library under libraries/",
    )

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
    # In a CHUMICRO_RAW_OUTPUT child the parent reads our stdout through
    # a pipe, which Python block-buffers.  Plain print() in run_command
    # echoes, the rolled-up summary, and the coverage Hint would then
    # sit in the userspace buffer while grandchild subprocesses (coverage
    # combine/report) write straight to the inherited fd, so the parent's
    # captured transcript shows their output before the command that
    # produced it.  Switch to line buffering so every print flushes at
    # the newline, keeping the transcript in emission order.
    if os.environ.get(_RAW_OUTPUT_ENV_VAR):
        sys.stdout.reconfigure(line_buffering=True)

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
            allow_no_tests=args.allow_no_tests,
        )

    if args.task == "verify-examples":
        return verify_examples(_resolve_scoped_packages(args))

    if args.task == "verify-demos":
        return verify_demos()

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
        return new_library(args.name, workbench=args.workbench)

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

    if args.task == "sweep-devices":
        return sweep_devices(
            device_ids=args.device_ids,
            demo=args.demo,
            skip_demo=args.skip_demo,
            functional=args.functional,
            skip_workbench=args.skip_workbench,
            library=args.library,
            deploy_mode=args.deploy_mode,
        )

    if args.task == "build":
        return build(package_workers=args.package_workers, quiet=args.quiet)

    if args.task == "check-api":
        return check_api(max_workers=args.max_workers, base=args.base)

    if args.task == "check-version":
        return check_version(base=args.base)

    if args.task == "bench":
        return bench(
            args.micropython_binary,
            args.circuitpython_binary,
            update_baseline=args.update_baseline,
        )

    # --- no-arg tasks ---
    no_arg: dict[str, Callable[[], int]] = {
        "setup": setup,
        "sync-ide": sync_ide,
        "lint": lint,
        "prepare-micropython": prepare_micropython,
        "prepare-circuitpython": prepare_circuitpython,
        "prepare-mpy-cross": prepare_mpy_cross,
        "check-dep-graph": check_dep_graph,
        "check-size": check_size,
    }

    if args.task in no_arg:
        return no_arg[args.task]()

    # Defense in depth: argparse rejects unknown subcommands before
    # reaching here, so this branch is unreachable in normal CLI use.
    print(f"Unknown task: {args.task}")  # pragma: no cover
    return 1  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
