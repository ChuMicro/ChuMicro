"""Output streaming + parallel-phase core for the task runner.

Four output modes route parallel-phase output to the user:

- ``quiet``: buffer every line; on ``finish()`` replay each phase's
  transcript under a ``== <label> ==`` header in submission order.
- ``interleave``: phase events and every line print live, prefixed with
  ``[label]``.  Default for non-TTY contexts (CI, redirected stdout).
- ``status``: phase events print live with elapsed time; per-line output
  is suppressed until a phase fails, then its transcript is dumped.
  Default for interactive consoles.
- ``raw``: used by the child of a subprocess re-invocation
  (``CHUMICRO_RAW_OUTPUT`` set); lines print raw for the parent to frame.

The dispatcher is chosen by :func:`_pick_dispatcher`.  Shared fan-out
sizing and slow-test thresholds live here too so every task module can
import them without a cycle.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from repo_layout import ROOT
from shared import stream_subprocess

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
