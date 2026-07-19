"""CPython host test lane: ``test`` and ``test-scripts`` plus the pytest
output-parsing infrastructure they share with the cross-runtime lanes."""

from __future__ import annotations

import argparse
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from repo_layout import (
    ROOT,
    coverage_args_for,
    discover_library_dirs,
    discover_package_dirs,
    pythonpath_environment,
)
from shared import run_command, stream_subprocess

from run_tasks._dispatch import (
    _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    _DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
    PYTHON,
    _pick_dispatcher,
    _run_parallel_phases,
    _Sink,
)


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


def register(subparsers, parents):
    """Register the CPython host test subcommands."""
    scope = parents["scope"]
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
