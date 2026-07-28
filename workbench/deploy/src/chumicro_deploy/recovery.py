"""Recovery layer around :class:`Deployer`.

Transport failures during deploy fall into a small set of classes
(port busy, CIRCUITPY drive missing, raw REPL unresponsive, rsync
balked mid-copy).  Most are recoverable when the user takes a
concrete physical action (close the program holding the port, tap
RESET, replug USB) and retries.  This module classifies a transport
exception into a :class:`DeployFailureKind`, looks up the canned
:class:`RecoveryPlan` for that kind, and wraps :class:`Deployer` in
a coaching loop that surfaces the plan and retries when retryable.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .macos_fskit import detect_fskit_wedge
from .protocol import DeviceTransportError, MidDeployDisconnected
from .recovery_kind import DeployFailureKind, RecoveryPlan
from .recovery_plans import PLANS
from .result import DeployResult

if TYPE_CHECKING:  # pragma: no cover -type-only
    from .deployer import Deployer
    from .sources import FileSource


#: Substrings that indicate the serial port couldn't be opened.
#: Covers pyserial's ``SerialException`` text, macOS / Linux errno
#: strings, and mpremote's subprocess error output (including
#: ``failed to access`` + ``it may be in use by another program``,
#: which mpremote emits for both missing and busy devices).
_PORT_UNAVAILABLE_PATTERNS = (
    "failed to open serial port",
    "could not open port",
    "no such file or directory",
    "resource busy",
    "resource temporarily unavailable",
    "permission denied",
    "device not configured",
    "failed to access",
    "it may be in use by another program",
)

#: CIRCUITPY drive detection / mount failures.  The "not writable"
#: variant covers the stale-mount case where ``/Volumes/CIRCUITPY``
#: lingers after a Finder eject (or macOS FSKit wedge): the
#: directory exists but writes fail with EACCES, which the transport
#: surfaces as "CIRCUITPY drive not found or not writable".
_CIRCUITPY_DRIVE_PATTERNS = (
    "circuitpy drive not found",
    "circuitpy drive not mounted",
    "circuitpy drive not found or not writable",
)

#: Raw REPL did not hand back its prompt or acknowledged garbage.
_RAW_REPL_PATTERNS = (
    "did not receive raw repl prompt",
    "raw repl did not acknowledge",
    "malformed raw repl response",
)

#: Port responds but no Python runtime is present (Arduino, raw
#: bootloader, or other firmware).
_NO_PYTHON_RUNTIME_PATTERNS = (
    "no python runtime detected",
    "no python runtime on",
    "board does not respond to python",
    "non-python firmware detected",
    "unknown firmware on",
)

#: Insufficient RAM for inline (RAM-mode) payload.  Catches both
#: the transport's pre-check and a raw ``MemoryError`` coming back
#: from the board.
_INSUFFICIENT_MEMORY_PATTERNS = (
    "too little free ram",
    "memoryerror",
    "memory allocation failed",
)

#: Flash-mode copy to the CIRCUITPY drive failed.  rsync failures,
#: disk-full, read-only filesystem, I/O errors.
_FLASH_COPY_PATTERNS = (
    "rsync",
    "input/output error",
    "no space left on device",
    "read-only file system",
    "operation not permitted",
)

#: Subset of FLASH_COPY signals that are unambiguously about the drive's
#: *state* (full / read-only / I/O error).  These win over the broader
#: ``CIRCUITPY drive not found or not writable`` wrapper text the
#: transport emits (the drive is found, it just can't accept the
#: write), so the classifier checks them before
#: :data:`_CIRCUITPY_DRIVE_PATTERNS`.  ``rsync`` is included because an
#: rsync failure originates inside the flash copy path; the drive
#: itself is necessarily mounted by the time rsync runs.
_FLASH_DRIVE_STATE_PATTERNS = (
    "rsync",
    "no space left on device",
    "read-only file system",
    "input/output error",
)

#: A bootstrap chunk, entrypoint, or mpremote exec step reported an
#: error on the board.  User code (or a dep) raised.
_BOOTSTRAP_EXEC_PATTERNS = (
    "inline bootstrap chunk",
    "circuitpython reported an error",
    "device exec failed",
    "device deploy-execute failed",
    "mpremote command failed",
)

#: An mpremote subprocess exceeded its timeout; the board's USB-CDC
#: wedged mid-command.  Distinct from BOOTSTRAP_EXEC ("command failed"):
#: a retry without a physical replug just hangs for the same timeout, so
#: COMMAND_TIMED_OUT is non-retryable.
_COMMAND_TIMEOUT_PATTERNS = (
    "command timed out",
)

#: Deploy-call misconfiguration: wrong flag, missing file, etc.
#: These are programmer errors, not runtime conditions.  Classifier
#: only flags them to steer retry decisions; the message is what
#: the caller actually reads.
_CONFIGURATION_PATTERNS = (
    "must be called before",
    "missing from files",
    "does not support deploy_mode",
)

#: The import walker refused a deploy because an import resolved to no
#: deployed file and isn't a known device built-in.  The lead phrase is
#: emitted verbatim by :class:`chumicro_deploy.sources.UnresolvedImportError`
#: so the classifier routes it without coupling to the exception subclass.
_UNRESOLVED_IMPORT_PATTERNS = (
    "deploy refused: unresolved import",
)

#: Signature of a Python traceback embedded in an error message.
#: On CircuitPython RAM mode the raw REPL raises
#: ``CircuitpythonTransportError`` with the board's stderr inline,
#: including ``Traceback (most recent call last):``.  Detecting that
#: substring lets the classifier route user-code errors to
#: :attr:`DeployFailureKind.TRACEBACK_RETURNED` (non-retryable, "fix
#: source") regardless of whether they surface as an exception (CP
#: RAM) or a :class:`DeployResult` (MP mount, CP flash).
_TRACEBACK_IN_MESSAGE_PATTERN = "traceback (most recent call last)"


#: Ordered classification table.  Each row is ``(patterns, kind)``;
#: the first row whose any-substring matches ``str(error).lower()``
#: wins.  Order is load-bearing:
#:
#: 1. ``CONFIGURATION_ERROR`` first, because caller misuse messages often
#:    contain substrings that look like other kinds (e.g. "CIRCUITPY
#:    drive not found").
#: 2. ``TRACEBACK_RETURNED`` before bootstrap / flash buckets so a
#:    board-side traceback lands the same way whether CP RAM raised
#:    inline or CP flash / MP returned it on the DeployResult.
#: 3. ``FLASH_COPY_FAILED`` (drive-state subset) wins over
#:    ``CIRCUITPY_DRIVE_MISSING``: a found-but-full / read-only /
#:    I/O-erroring drive deserves "free up space / remount" coaching,
#:    not the generic "tap RESET" CIRCUITPY_DRIVE_MISSING gives.
#: 4. ``CIRCUITPY_DRIVE_MISSING`` before ``PORT_UNAVAILABLE``: the
#:    stale-mount error in _resolve_circuitpy_drive wraps a
#:    PermissionError whose text ("permission denied") would
#:    otherwise collide with the generic port table.
#: 5. ``NO_PYTHON_RUNTIME`` before ``PORT_UNAVAILABLE`` /
#:    ``RAW_REPL_UNRESPONSIVE``: explicit "no python here" is strictly
#:    more specific than "port unreachable" or "REPL silent", and
#:    points at a different recovery (install-firmware, not plug-in).
#: 6. ``COMMAND_TIMED_OUT`` before ``BOOTSTRAP_EXEC_FAILED``: both carry
#:    "mpremote command ..." text, but a timeout is a wedged-CDC hang
#:    (non-retryable, replug), not a board-side exec error.
_CLASSIFICATION_TABLE: tuple[
    tuple[tuple[str, ...], DeployFailureKind], ...
] = (
    (_CONFIGURATION_PATTERNS, DeployFailureKind.CONFIGURATION_ERROR),
    (_UNRESOLVED_IMPORT_PATTERNS, DeployFailureKind.UNRESOLVED_IMPORT),
    ((_TRACEBACK_IN_MESSAGE_PATTERN,), DeployFailureKind.TRACEBACK_RETURNED),
    (_FLASH_DRIVE_STATE_PATTERNS, DeployFailureKind.FLASH_COPY_FAILED),
    (_CIRCUITPY_DRIVE_PATTERNS, DeployFailureKind.CIRCUITPY_DRIVE_MISSING),
    (_NO_PYTHON_RUNTIME_PATTERNS, DeployFailureKind.NO_PYTHON_RUNTIME),
    (_PORT_UNAVAILABLE_PATTERNS, DeployFailureKind.PORT_UNAVAILABLE),
    (_RAW_REPL_PATTERNS, DeployFailureKind.RAW_REPL_UNRESPONSIVE),
    (_INSUFFICIENT_MEMORY_PATTERNS, DeployFailureKind.INSUFFICIENT_MEMORY),
    (_FLASH_COPY_PATTERNS, DeployFailureKind.FLASH_COPY_FAILED),
    (_COMMAND_TIMEOUT_PATTERNS, DeployFailureKind.COMMAND_TIMED_OUT),
    (_BOOTSTRAP_EXEC_PATTERNS, DeployFailureKind.BOOTSTRAP_EXEC_FAILED),
)


def classify_deploy_failure(error: Exception) -> DeployFailureKind:
    """Map a deploy-path exception to a :class:`DeployFailureKind`.

    The classifier is intentionally string-based: it inspects
    ``str(error).lower()`` against :data:`_CLASSIFICATION_TABLE`.
    That keeps the classifier decoupled from the specific exception
    subclass, which matters because a raised
    ``CircuitpythonTransportError`` often wraps a ``SerialException``
    or ``OSError`` whose text is the real signal.

    Returns :attr:`DeployFailureKind.UNKNOWN` when no row matches.
    """
    # Typed disconnect subclasses skip the string-pattern dance.
    # They were raised because the device dropped, period.  Routes
    # to PORT_UNAVAILABLE, where the recovery is "plug it back in".
    if isinstance(error, MidDeployDisconnected):
        return DeployFailureKind.PORT_UNAVAILABLE

    message = str(error).lower()
    for patterns, kind in _CLASSIFICATION_TABLE:
        if any(pattern in message for pattern in patterns):
            return kind
    return DeployFailureKind.UNKNOWN


@dataclass(frozen=True)
class PortHolder:
    """A process currently holding a serial port open.

    Returned by :func:`diagnose_port_holders` so output to the user
    can name the process blocking the deploy instead of the generic
    "close the app holding the port" hint.

    Attributes:
        pid: Process id reported by ``lsof``.
        command: Full command line via ``ps -o command=``.  More
            informative than ``lsof``'s short ``c`` field for
            distinguishing stale chumicro processes from an external
            app explicitly opened by the user.
    """

    pid: int
    command: str


#: Recognize ``/dev/cu.X`` (macOS) and ``/dev/ttyACM0`` /
#: ``/dev/ttyUSB0`` (Linux) paths embedded in transport-error text.
#: The character class is restricted to alphanumerics + ``.`` / ``_``
#: / ``-`` so trailing ``:`` (from ``"/dev/ttyACM0: Resource busy"``)
#: and ``'`` / ``"`` (from quoted error strings) don't get pulled
#: into the captured path.
_PORT_PATH_RE = re.compile(r"/dev/(?:cu|tty)[A-Za-z0-9._-]+")

#: Substrings that flag a port-holding process as "probably ours":
#: a stale chumicro-deploy or mpremote subprocess from a previous
#: run, vs. an external app the user explicitly opened (Mu, Thonny,
#: VS Code's serial console).
_LIKELY_CHUMICRO_KEYWORDS = (
    "chumicro-deploy",
    "chumicro_workspace",
    "mpremote",
    "run.py deploy",  # noqa: CHU006 - workspace shim command name is data here, not prose
)


def _extract_port_path_from_error(error: BaseException) -> str | None:
    """Find the first ``/dev/(cu|tty)*`` path in an error's text.

    Transport errors embed the port path in their message
    (mpremote's stderr, pyserial's ``SerialException``).  Returns
    ``None`` when no path is found.
    """
    match = _PORT_PATH_RE.search(str(error))
    return match.group(0) if match else None


def _full_command_for_pid(
    pid: int,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str | None:
    """Return the full command line for *pid* via ``ps``, or ``None``.

    ``ps -p <pid> -o command=`` is portable across macOS and Linux.
    ``None`` covers the common races (process exited between lsof
    and ps), unsupported platforms, and missing ``ps`` binary.
    """
    try:
        result = runner(  # noqa: S603 - args fully controlled
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, check=False, timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def diagnose_port_holders(
    port_path: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[PortHolder]:
    """Return processes currently holding *port_path* open.

    Uses ``lsof -F pcn <port>`` on POSIX.  The output format is one
    field per line tagged with a single character (``p`` for PID,
    ``c`` for short command, ``n`` for path).  Each PID record
    starts with a ``p`` line, and subsequent ``c`` / ``n`` lines belong
    to it until the next ``p`` or EOF.

    Returns an empty list on Windows (no portable equivalent
    without ``handle.exe``), when ``lsof`` isn't installed, when
    the port is not held, or on any subprocess failure.  The
    caller treats absence of holders as "we couldn't tell, fall
    through to the generic recovery hint" rather than an error.

    A deploy interrupted by Ctrl-C that leaves an orphan
    chumicro-deploy / mpremote subprocess holding the port surfaces
    as "failed to access ... it may be in use by another program".
    Showing the PID lets the user kill the right thing without
    running ``lsof`` themselves.
    """
    if sys.platform.startswith("win"):
        return []
    try:
        result = runner(  # noqa: S603 - args fully controlled
            ["lsof", "-F", "pcn", port_path],
            capture_output=True, text=True, check=False, timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    holders: list[PortHolder] = []
    current_pid: int | None = None
    for line in result.stdout.splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p":
            try:
                current_pid = int(value)
            except ValueError:
                current_pid = None
        elif tag == "c" and current_pid is not None:
            full_command = _full_command_for_pid(current_pid, runner=runner)
            holders.append(
                PortHolder(
                    pid=current_pid,
                    command=full_command or value,
                ),
            )
            current_pid = None
    return holders


def _looks_like_chumicro(holder: PortHolder) -> bool:
    """Heuristic: is *holder* a stale chumicro-deploy / mpremote process?"""
    command = holder.command
    return any(keyword in command for keyword in _LIKELY_CHUMICRO_KEYWORDS)


def recovery_plan_for(kind: DeployFailureKind) -> RecoveryPlan:
    """Return the canned :class:`RecoveryPlan` for *kind*."""
    return PLANS[kind]


#: Default attempts for :class:`RecoveringDeployer` with a prompt.
#: Three matches the common recovery pattern: user had another
#: program open, closes it, retries once, maybe needs a RESET.
_DEFAULT_MAX_ATTEMPTS = 3


class RecoveringDeployer:
    """:class:`Deployer` wrapper that classifies failures and coaches recovery.

    Two modes selected by the *prompt* argument:

    - **Non-interactive** (``prompt=None``, the default): runs once,
      prints the classified failure + ordered fix steps on a
      transport error, then re-raises.
    - **Interactive** (``prompt=input`` or any callable taking the
      prompt text and returning the user's reply): runs up to
      *max_attempts* times, asks between attempts.  An empty / pure-
      whitespace reply continues; any reply starting with ``q``,
      ``a``, or ``e`` aborts.

    On a :class:`DeployResult` with ``success=False`` and a
    ``traceback``, both modes print the traceback + the
    ``TRACEBACK_RETURNED`` plan and return the result unchanged.  A
    source-level bug isn't something retrying the same bytes will fix.

    Args:
        deployer: Underlying :class:`Deployer` that owns the device
            and transport construction.
        prompt: Callable that asks the user whether to retry.  ``None``
            (default) is non-interactive: report once and re-raise.
            Pass :func:`input` (or any ``(str) -> str`` callable) for
            the interactive retry loop.
        max_attempts: Ceiling on retry attempts when *prompt* is set.
            Ignored in non-interactive mode (always 1 attempt).
        output: Injectable output sink.  Defaults to :func:`print`.
        fskit_wedge_detector: Injectable probe for the macOS FSKit
            wedge.  Promotes ``CIRCUITPY_DRIVE_MISSING`` failures to
            ``MACOS_FSKIT_WEDGED`` when the detector fires, so the
            recovery plan points the user at the right fix.
    """

    def __init__(
        self,
        deployer: Deployer,
        *,
        prompt: Callable[[str], str] | None = None,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        output: Callable[[str], None] = print,
        fskit_wedge_detector: Callable[[], bool] = detect_fskit_wedge,
    ) -> None:
        if max_attempts < 1:
            raise ValueError(
                f"max_attempts must be >= 1, got {max_attempts}"
            )
        self._deployer = deployer
        self._prompt = prompt
        self._max_attempts = max_attempts if prompt is not None else 1
        self._output = output
        self._fskit_wedge_detector = fskit_wedge_detector

    @property
    def deployer(self) -> Deployer:
        """The underlying non-recovery :class:`Deployer`."""
        return self._deployer

    def deploy_diff(
        self,
        source: FileSource,
        *,
        clean: bool = True,
        wipe: bool = False,
        on_progress: Callable[[float, str], None] | None = None,
        on_file_staged: Callable[[str], None] | None = None,
        on_file_deleted: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
        tail_seconds: float | None = None,
        force_deploy_mode: str | None = None,
    ) -> DeployResult:
        """Diff-deploy *source* with classify / coach / (optional retry)."""
        return self._run(
            lambda: self._deployer.deploy_diff(
                source,
                clean=clean,
                wipe=wipe,
                on_progress=on_progress,
                on_file_staged=on_file_staged,
                on_file_deleted=on_file_deleted,
                on_execute_line=on_execute_line,
                tail_seconds=tail_seconds,
                force_deploy_mode=force_deploy_mode,
            ),
        )

    def _run(self, call: Callable[[], DeployResult]) -> DeployResult:
        """Drive *call* through the classify / coach / (optional retry) loop.

        Non-interactive mode (``prompt=None``) loops once: report the
        failure (with a ``"1/1"`` attempt header that makes the no-
        retry contract explicit in the output) and re-raise.
        Interactive mode loops up to ``max_attempts`` and asks the
        prompt callable between attempts.  Every exit path returns
        or raises from inside the loop.
        """
        attempt = 0
        while attempt < self._max_attempts:
            attempt += 1
            try:
                result = call()
            except DeviceTransportError as error:
                kind = self._resolve_kind(error)
                plan = recovery_plan_for(kind)
                self._report_failure(
                    attempt, self._max_attempts, error, kind, plan,
                )
                if not plan.retryable:
                    raise
                if attempt >= self._max_attempts:
                    raise
                if self._prompt is None or not self._ask_retry(attempt):
                    raise
                continue

            if not result.success and result.traceback is not None:
                plan = recovery_plan_for(DeployFailureKind.TRACEBACK_RETURNED)
                self._report_traceback(attempt, result.traceback, plan)
            return result

        raise AssertionError("unreachable")  # pragma: no cover

    def _ask_retry(self, attempt: int) -> bool:
        """Ask the user whether to retry, returning ``True`` to continue.

        Any response starting with ``q`` (``quit``), ``a`` (``abort``),
        or ``e`` (``exit``) is interpreted as "stop retrying".  Empty
        input (plain Enter) is the expected continue path.  Only
        called in interactive mode (``self._prompt is not None``).
        """
        assert self._prompt is not None
        response = self._prompt(
            f"[chumicro-deploy] Fix the condition above and press "
            f"Enter to retry (attempt {attempt + 1}/"
            f"{self._max_attempts}), or type 'quit' to abort: "
        )
        normalized = response.strip().lower()
        if not normalized:
            return True
        first_char = normalized[0]
        return first_char not in ("q", "a", "e")

    def _resolve_kind(self, error: Exception) -> DeployFailureKind:
        """Classify *error* and promote ``CIRCUITPY_DRIVE_MISSING`` to
        ``MACOS_FSKIT_WEDGED`` when the macOS FSKit detector fires.
        """
        kind = classify_deploy_failure(error)
        if (
            kind is DeployFailureKind.CIRCUITPY_DRIVE_MISSING
            and self._fskit_wedge_detector()
        ):
            kind = DeployFailureKind.MACOS_FSKIT_WEDGED
        return kind

    def _report_failure(
        self,
        attempt: int,
        max_attempts: int,
        error: Exception,
        kind: DeployFailureKind,
        plan: RecoveryPlan,
    ) -> None:
        """Print the coached failure report for a transport error."""
        self._output("")
        self._output(
            f"[chumicro-deploy] Attempt {attempt}/{max_attempts} "
            f"failed: {kind.value}"
        )
        self._output(f"[chumicro-deploy] {plan.headline}")
        self._output(f"[chumicro-deploy] Underlying error: {error}")
        if kind is DeployFailureKind.PORT_UNAVAILABLE:
            self._report_port_holders(error)
        self._output("[chumicro-deploy] Try this:")
        for step in plan.fix_steps:
            self._output(f"  - {step}")

    def _report_port_holders(self, error: Exception) -> None:
        """Print the lsof diagnosis for ``PORT_UNAVAILABLE`` failures.

        Pulls the port path out of *error*'s text, runs
        :func:`diagnose_port_holders`, and emits a labeled section
        when something is holding the port.  Silently no-ops when
        the port can't be identified, lsof is unavailable, or the
        port has no current holders (the user-action recovery
        steps below will still surface the generic hint).
        """
        port_path = _extract_port_path_from_error(error)
        if port_path is None:
            return
        try:
            holders = diagnose_port_holders(port_path)
        except Exception:  # noqa: BLE001 - diagnosis is best-effort
            return
        if not holders:
            return
        self._output(
            f"[chumicro-deploy] {port_path} is currently held by:",
        )
        for holder in holders:
            self._output(f"  PID {holder.pid}: {holder.command}")
        likely_ours = next(
            (holder for holder in holders if _looks_like_chumicro(holder)),
            None,
        )
        if likely_ours is not None:
            self._output(
                f"[chumicro-deploy] Looks like a stale chumicro-deploy "
                f"or mpremote process from a previous run.  "
                f"Terminate it with:  kill {likely_ours.pid}",
            )

    def _report_traceback(
        self,
        attempt: int,
        traceback_text: str,
        plan: RecoveryPlan,
    ) -> None:
        """Print the coached report for a board-side traceback."""
        self._output("")
        self._output(
            f"[chumicro-deploy] Attempt {attempt} completed, but the "
            f"entrypoint raised on the board."
        )
        self._output(f"[chumicro-deploy] {plan.headline}")
        self._output("[chumicro-deploy] --- traceback ---")
        self._output(traceback_text)
        self._output("[chumicro-deploy] Try this:")
        for step in plan.fix_steps:
            self._output(f"  - {step}")
