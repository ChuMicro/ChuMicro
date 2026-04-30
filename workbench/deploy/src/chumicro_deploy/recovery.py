"""Interactive recovery layer around :class:`Deployer`.

Transport failures during deploy come in a small number of flavours —
port busy, CIRCUITPY drive missing, raw REPL unresponsive, rsync
balked mid-copy.  All but a few are recoverable by the user taking
a concrete physical action (close a program holding the port, tap
RESET, replug USB) and retrying.

This module provides:

- :class:`DeployFailureKind` — categorical enum of deploy failures.
- :func:`classify_deploy_failure` — string-match classifier that
  maps a transport exception onto one of the kinds.
- :class:`RecoveryPlan` + :func:`recovery_plan_for` — canned
  headline + ordered fix-steps per kind.
- :class:`InteractiveDeployer` — sibling of :class:`Deployer` that
  catches transport failures, surfaces the plan, prompts the user
  to retry after they've fixed the physical condition, and loops
  up to a configurable attempt ceiling.

Keeping this as a sibling instead of baking it into
:class:`Deployer` preserves the deterministic programmatic API
that scripts like ``device_testing.py`` depend on.  Interactive
use (the ``chumicro-deploy`` CLI, the workspace ``run.py deploy``
shim, direct human invocation) opts in by instantiating
:class:`InteractiveDeployer` instead.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .circuitpython_transport import CircuitpythonTransportError
from .macos_fskit import MACOS_FSKIT_RECOVERY_COMMAND, detect_fskit_wedge
from .micropython_transport import MicropythonTransportError
from .result import DeployResult

if TYPE_CHECKING:  # pragma: no cover — type-only
    from .deployer import Deployer
    from .sources import FileSource


class DeployFailureKind(Enum):
    """Broad categories of deploy failures, keyed to recovery guidance.

    The classifier collapses the ~20 distinct
    :class:`CircuitpythonTransportError` sites and MP transport
    errors into these buckets.  Each bucket has a canned
    :class:`RecoveryPlan`; :class:`InteractiveDeployer` consults the
    plan's ``retryable`` flag to decide whether to loop or bail.
    """

    PORT_UNAVAILABLE = "port_unavailable"
    RAW_REPL_UNRESPONSIVE = "raw_repl_unresponsive"
    CIRCUITPY_DRIVE_MISSING = "circuitpy_drive_missing"
    MACOS_FSKIT_WEDGED = "macos_fskit_wedged"
    FLASH_COPY_FAILED = "flash_copy_failed"
    BOOTSTRAP_EXEC_FAILED = "bootstrap_exec_failed"
    INSUFFICIENT_MEMORY = "insufficient_memory"
    TRACEBACK_RETURNED = "traceback_returned"
    CONFIGURATION_ERROR = "configuration_error"
    UNKNOWN = "unknown"


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
#: lingers after a Finder eject (or macOS FSKit wedge) — the
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
#: transport emits — the drive is found, it just can't accept the
#: write — so the classifier checks them before
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

#: Deploy-call misconfiguration — wrong flag, missing file, etc.
#: These are programmer errors, not runtime conditions.  Classifier
#: only flags them to steer retry decisions; the message is what
#: the caller actually reads.
_CONFIGURATION_PATTERNS = (
    "must be called before",
    "missing from files",
    "does not support deploy_mode",
)

#: Signature of a Python traceback embedded in an error message.
#: On CircuitPython RAM mode the raw REPL raises
#: ``CircuitpythonTransportError`` with the board's stderr inline —
#: including ``Traceback (most recent call last):``.  Detecting that
#: substring lets the classifier route user-code errors to
#: :attr:`DeployFailureKind.TRACEBACK_RETURNED` (non-retryable, "fix
#: source") regardless of whether they surface as an exception (CP
#: RAM) or a :class:`DeployResult` (MP mount, CP flash).
_TRACEBACK_IN_MESSAGE_PATTERN = "traceback (most recent call last)"


def classify_deploy_failure(error: Exception) -> DeployFailureKind:
    """Map a deploy-path exception to a :class:`DeployFailureKind`.

    The classifier is intentionally string-based — it inspects
    ``str(error).lower()`` for any pattern in the per-kind tables
    above.  That keeps the classifier decoupled from the specific
    exception subclass, which matters because a raised
    ``CircuitpythonTransportError`` often wraps a ``SerialException``
    or ``OSError`` whose text is the real signal.

    Order of checks matters: the most specific kinds
    (CIRCUITPY drive, raw REPL, memory) are tested before the
    broader buckets (flash copy, bootstrap exec) so a message that
    happens to share a substring with a looser bucket still lands
    in the right place.

    Args:
        error: Any exception raised from the deploy path.

    Returns:
        :attr:`DeployFailureKind.UNKNOWN` when no pattern matches —
        :class:`InteractiveDeployer` treats that as retryable so
        the user isn't locked out of an unclassified hiccup.
    """
    # Typed disconnect subclasses skip the string-pattern dance —
    # they were raised because the device dropped, period.  Routes
    # to PORT_UNAVAILABLE because the user-facing fix is the same
    # ("plug it back in").  isinstance check is import-light because
    # the subclasses live in their owning transport modules and
    # this module already imports them.
    from .circuitpython_transport import CircuitpythonMidDeployDisconnected
    from .micropython_transport import MicropythonMidDeployDisconnected

    if isinstance(
        error,
        (CircuitpythonMidDeployDisconnected, MicropythonMidDeployDisconnected),
    ):
        return DeployFailureKind.PORT_UNAVAILABLE

    message = str(error).lower()
    # Check CONFIGURATION first — these messages often contain
    # substrings that look like other kinds (e.g. "CIRCUITPY drive
    # not found — pass circuitpy_drive_path") but really mean the
    # caller misconfigured the deploy.
    for pattern in _CONFIGURATION_PATTERNS:
        if pattern in message:
            return DeployFailureKind.CONFIGURATION_ERROR
    # An embedded Python traceback is a user-code failure no matter
    # which wrapper exception carries it.  Route to TRACEBACK_RETURNED
    # before the broader bootstrap / flash-copy buckets so CP RAM mode
    # (which raises with the traceback inline) lands alongside CP
    # flash + MP (which return a DeployResult with a traceback field).
    if _TRACEBACK_IN_MESSAGE_PATTERN in message:
        return DeployFailureKind.TRACEBACK_RETURNED
    # Drive *state* failures (disk-full, read-only, I/O error, rsync)
    # win over the generic "CIRCUITPY drive not found or not writable"
    # wrapper.  The transport's _resolve_circuitpy_drive probes the
    # mount with a tiny write before staging; if that probe surfaces
    # an ENOSPC / EROFS / EIO, the drive is found and its problem is
    # specific.  Routing to FLASH_COPY_FAILED here surfaces the
    # right coaching ("free up space", "remount writable") instead of
    # CIRCUITPY_DRIVE_MISSING's "tap RESET to remount".
    for pattern in _FLASH_DRIVE_STATE_PATTERNS:
        if pattern in message:
            return DeployFailureKind.FLASH_COPY_FAILED
    # CIRCUITPY drive checks come BEFORE port-unavailable: the stale
    # mount path in CircuitpythonTransport._resolve_circuitpy_drive
    # raises with a message that starts "CIRCUITPY drive not found
    # or not writable" but wraps a PermissionError whose text
    # ("permission denied") collides with the generic port patterns.
    # A message that literally says "CIRCUITPY drive" should never
    # land in PORT_UNAVAILABLE — the drive prefix is strictly more
    # informative than the nested errno string.
    for pattern in _CIRCUITPY_DRIVE_PATTERNS:
        if pattern in message:
            return DeployFailureKind.CIRCUITPY_DRIVE_MISSING
    for pattern in _PORT_UNAVAILABLE_PATTERNS:
        if pattern in message:
            return DeployFailureKind.PORT_UNAVAILABLE
    for pattern in _RAW_REPL_PATTERNS:
        if pattern in message:
            return DeployFailureKind.RAW_REPL_UNRESPONSIVE
    for pattern in _INSUFFICIENT_MEMORY_PATTERNS:
        if pattern in message:
            return DeployFailureKind.INSUFFICIENT_MEMORY
    for pattern in _FLASH_COPY_PATTERNS:
        if pattern in message:
            return DeployFailureKind.FLASH_COPY_FAILED
    for pattern in _BOOTSTRAP_EXEC_PATTERNS:
        if pattern in message:
            return DeployFailureKind.BOOTSTRAP_EXEC_FAILED
    return DeployFailureKind.UNKNOWN


@dataclass(frozen=True)
class RecoveryPlan:
    """User-facing guidance for a single :class:`DeployFailureKind`.

    Attributes:
        headline: One-line summary the user reads first.
        fix_steps: Ordered physical actions the user can take.  Each
            step is a short imperative sentence; the interactive
            deployer renders them as a bulleted list.
        retryable: ``True`` when retrying after the user takes the
            fix steps is worth attempting.  ``False`` for hard
            failures (wrong flags, runtime tracebacks, too-small
            boards) where a retry would change nothing.
    """

    headline: str
    fix_steps: tuple[str, ...]
    retryable: bool


_PLANS: dict[DeployFailureKind, RecoveryPlan] = {
    DeployFailureKind.PORT_UNAVAILABLE: RecoveryPlan(
        headline="The serial port is unavailable.",
        fix_steps=(
            "Check that the board is plugged into USB.",
            "Close any app that may be holding the port — Mu, Thonny, "
            "screen/minicom, another mpremote, PyCharm or VS Code "
            "serial console.",
            "If the port still does not appear, tap the board's "
            "RESET button and wait 2–3 seconds for re-enumeration.",
        ),
        retryable=True,
    ),
    DeployFailureKind.RAW_REPL_UNRESPONSIVE: RecoveryPlan(
        headline="The board's REPL did not respond.",
        fix_steps=(
            "Tap the board's RESET button and wait a second.",
            "If CircuitPython dropped into safe mode, press any key "
            "over a serial terminal to exit safe mode, then retry.",
            "If the board is stuck running user code that ignores "
            "Ctrl-C, hold RESET for 2 seconds or unplug + replug "
            "the USB cable.",
        ),
        retryable=True,
    ),
    DeployFailureKind.CIRCUITPY_DRIVE_MISSING: RecoveryPlan(
        headline="The CIRCUITPY drive is not mounted.",
        fix_steps=(
            "Tap RESET on the board — this re-exposes the drive "
            "whether it was hidden by flash deploy mode or ejected "
            "manually from Finder.",
            "If the board has no RESET button, unplug + replug it.",
            "If the board isn't running CircuitPython, reflash it "
            "first with `chumicro-deploy flash --method uf2`.",
        ),
        retryable=True,
    ),
    DeployFailureKind.MACOS_FSKIT_WEDGED: RecoveryPlan(
        headline=(
            "macOS FSKit / DiskArbitration is wedged — CIRCUITPY drives "
            "cannot mount until the stuck daemons are killed."
        ),
        fix_steps=(
            "Paste this into another terminal (it needs sudo):",
            f"    {MACOS_FSKIT_RECOVERY_COMMAND}",
            "The system daemons respawn via launchd; the "
            "launchctl kickstart -k bounces the per-user agent "
            "(which does not auto-respawn).  Pending CIRCUITPY "
            "drives will mount + become readable.  Press Enter "
            "here to retry the deploy.",
            "Heads-up: after the paste your drives will be fully "
            "functional (mounted at /Volumes, readable, writable, "
            "and chumicro-deploy works against them), but on "
            "recent macOS they may NOT appear in Finder's "
            "Locations sidebar.  That's an Apple FSKit-Finder "
            "regression unrelated to this recovery — reach them "
            "via Shift+Cmd+C (Computer view) or drag one into "
            "the Favorites sidebar section.",
            "If the wedge persists after the command, reboot — "
            "that always clears it and also resets the Finder "
            "sidebar classifier.",
            "Full write-up (why each daemon is killed, what the "
            "Finder sidebar regression is, and when to reboot) "
            "lives at "
            "https://github.com/ChuMicro/ChuMicro/blob/main/"
            "docs/troubleshooting/macos-circuitpy.md.",
        ),
        retryable=True,
    ),
    DeployFailureKind.FLASH_COPY_FAILED: RecoveryPlan(
        headline="Copying files to the CIRCUITPY drive failed.",
        fix_steps=(
            "The drive may have auto-ejected mid-copy — "
            "CircuitPython's autoreload can remount while a write "
            "is in flight.  Tap RESET and retry.",
            "Check free space on the drive if the payload is larger "
            "than a few KiB.",
            "If the drive became read-only, unplug + replug to "
            "remount read-write.",
        ),
        retryable=True,
    ),
    DeployFailureKind.BOOTSTRAP_EXEC_FAILED: RecoveryPlan(
        headline="The code raised on the board during startup.",
        fix_steps=(
            "Read the traceback or stderr above to spot the error.",
            "If it's a bug in your source, fix it and retry.",
            "If it looks transient (bad frame, serial glitch, "
            "partial mount), tap RESET and retry.",
        ),
        retryable=True,
    ),
    DeployFailureKind.INSUFFICIENT_MEMORY: RecoveryPlan(
        headline=(
            "The board does not have enough free RAM for inline "
            "(RAM-mode) deploy."
        ),
        fix_steps=(
            "Re-run with `--deploy-mode flash` to land the files on "
            "the CIRCUITPY drive instead — flash mode is the "
            "built-in escape hatch for payloads that do not fit.",
            "Reduce payload size by trimming unused imports, or "
            "split the deploy across multiple runs.",
        ),
        retryable=False,
    ),
    DeployFailureKind.CONFIGURATION_ERROR: RecoveryPlan(
        headline="The deploy call was misconfigured.",
        fix_steps=(
            "This is a code-level misuse, not a runtime failure.  "
            "Check the error message above for the exact parameter "
            "that's missing or wrong.  A retry will not change the "
            "outcome until the call-site is fixed.",
        ),
        retryable=False,
    ),
    DeployFailureKind.TRACEBACK_RETURNED: RecoveryPlan(
        headline="The entrypoint ran but raised a traceback.",
        fix_steps=(
            "Read the traceback above, fix the source, and redeploy.",
            "To poke at the board's state live, open a REPL — "
            "`screen <port> 115200`, `minicom`, `mpremote`, or your "
            "IDE's serial console.",
        ),
        retryable=False,
    ),
    DeployFailureKind.UNKNOWN: RecoveryPlan(
        headline="An unclassified deploy failure occurred.",
        fix_steps=(
            "The full error is above.  As a first cut at recovery, "
            "tap RESET and retry.",
            "If you can reproduce this, please file a report with "
            "the message text and the board involved.",
        ),
        retryable=True,
    ),
}


def recovery_plan_for(kind: DeployFailureKind) -> RecoveryPlan:
    """Return the canned :class:`RecoveryPlan` for *kind*."""
    return _PLANS[kind]


#: Default number of deploy attempts before :class:`InteractiveDeployer`
#: gives up and re-raises.  Three matches the typical "user had
#: another program open, closes it, retries once, maybe needs a RESET"
#: pattern observed across CP + MP boards.
_DEFAULT_MAX_ATTEMPTS = 3


class InteractiveDeployer:
    """:class:`Deployer` wrapper that coaches the user through failures.

    On :class:`CircuitpythonTransportError` or
    :class:`MicropythonTransportError`, this deployer classifies the
    failure, prints a headline + recovery steps, and (when the plan
    is retryable) prompts the user to fix the condition and press
    Enter to retry.  After ``max_attempts`` attempts the last
    exception re-raises.

    On a :class:`DeployResult` with ``success=False`` and a
    ``traceback``, the deployer prints the traceback + a
    ``TRACEBACK_RETURNED`` plan but returns the result unchanged —
    a source-level bug isn't something retrying the same bytes
    will fix.

    Args:
        deployer: Underlying :class:`Deployer` that owns the device
            and transport construction.
        max_attempts: Ceiling on retry attempts.  Defaults to 3.
        prompt: Injectable prompt callable.  Defaults to
            :func:`input`.  Return an empty / whitespace-only string
            to continue, or ``"quit"`` / ``"q"`` / ``"abort"`` /
            ``"exit"`` to stop retrying and re-raise the last error.
        output: Injectable output sink.  Defaults to
            :func:`print` (so messages go to stdout).  Tests inject
            a list-append to make assertions.
        fskit_wedge_detector: Injectable probe for the macOS
            FSKit / DiskArbitration wedge (see :mod:`macos_fskit`).
            Called only on ``CIRCUITPY_DRIVE_MISSING`` failures; if
            it returns ``True``, the kind is promoted to
            :attr:`DeployFailureKind.MACOS_FSKIT_WEDGED` so the
            user sees the exact ``sudo`` command that unsticks the
            daemons instead of the generic "tap RESET" steps.
    """

    def __init__(
        self,
        deployer: Deployer,
        *,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        prompt: Callable[[str], str] = input,
        output: Callable[[str], None] = print,
        fskit_wedge_detector: Callable[[], bool] = detect_fskit_wedge,
    ) -> None:
        if max_attempts < 1:
            raise ValueError(
                f"max_attempts must be >= 1, got {max_attempts}"
            )
        self._deployer = deployer
        self._max_attempts = max_attempts
        self._prompt = prompt
        self._output = output
        self._fskit_wedge_detector = fskit_wedge_detector

    @property
    def deployer(self) -> Deployer:
        """The underlying non-interactive :class:`Deployer`."""
        return self._deployer

    def deploy(
        self,
        source: FileSource,
        *,
        on_progress: Callable[[float, str], None] | None = None,
        on_file_staged: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
    ) -> DeployResult:
        """Deploy *source*, prompting the user to recover on failure.

        Signature matches :meth:`Deployer.deploy` exactly — all
        callback parameters are forwarded.  The only new behaviour
        is the retry loop + user prompts on classified failures.
        """
        return self._retry_loop(
            lambda: self._deployer.deploy(
                source,
                on_progress=on_progress,
                on_file_staged=on_file_staged,
                on_execute_line=on_execute_line,
            ),
        )

    def deploy_diff(
        self,
        source: FileSource,
        *,
        wipe: bool = False,
        on_progress: Callable[[float, str], None] | None = None,
        on_file_staged: Callable[[str], None] | None = None,
        on_file_deleted: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
    ) -> DeployResult:
        """Diff-deploy *source*, prompting the user to recover on failure.

        Signature matches :meth:`Deployer.deploy_diff` exactly — all
        callback parameters and the ``wipe`` flag are forwarded.  The
        only new behaviour is the retry loop + user prompts on
        classified failures, identical in shape to :meth:`deploy`.
        """
        return self._retry_loop(
            lambda: self._deployer.deploy_diff(
                source,
                wipe=wipe,
                on_progress=on_progress,
                on_file_staged=on_file_staged,
                on_file_deleted=on_file_deleted,
                on_execute_line=on_execute_line,
            ),
        )

    def _retry_loop(
        self, call: Callable[[], DeployResult],
    ) -> DeployResult:
        """Drive *call* through the classify / coach / retry loop.

        Same shape for both :meth:`deploy` and :meth:`deploy_diff` —
        only the inner deployer call differs, so the loop body lives
        here once and the public methods are thin lambda wrappers.
        """
        attempt = 0
        last_error: Exception | None = None
        while attempt < self._max_attempts:
            attempt += 1
            try:
                result = call()
            except (
                CircuitpythonTransportError,
                MicropythonTransportError,
            ) as error:
                last_error = error
                kind = classify_deploy_failure(error)
                if (
                    kind is DeployFailureKind.CIRCUITPY_DRIVE_MISSING
                    and self._fskit_wedge_detector()
                ):
                    kind = DeployFailureKind.MACOS_FSKIT_WEDGED
                plan = recovery_plan_for(kind)
                self._report_failure(attempt, error, kind, plan)
                if not plan.retryable:
                    raise
                if attempt >= self._max_attempts:
                    raise
                if not self._ask_retry(attempt):
                    raise
                continue

            if not result.success and result.traceback is not None:
                plan = recovery_plan_for(
                    DeployFailureKind.TRACEBACK_RETURNED,
                )
                self._report_traceback(attempt, result.traceback, plan)
            return result

        # Unreachable in practice — the except branch always raises
        # once attempts are exhausted — but keep a deterministic
        # fallback so static analysis is happy.
        assert last_error is not None
        raise last_error  # pragma: no cover

    def _report_failure(
        self,
        attempt: int,
        error: Exception,
        kind: DeployFailureKind,
        plan: RecoveryPlan,
    ) -> None:
        """Print the coached failure report for a transport error."""
        self._output("")
        self._output(
            f"[chumicro-deploy] Attempt {attempt}/{self._max_attempts} "
            f"failed: {kind.value}"
        )
        self._output(f"[chumicro-deploy] {plan.headline}")
        self._output(f"[chumicro-deploy] Underlying error: {error}")
        self._output("[chumicro-deploy] Try this:")
        for step in plan.fix_steps:
            self._output(f"  - {step}")

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

    def _ask_retry(self, attempt: int) -> bool:
        """Ask the user whether to retry; return ``True`` to continue.

        Any response starting with ``q`` (``quit``), ``a`` (``abort``),
        or ``e`` (``exit``) is interpreted as "stop retrying".  Empty
        input (plain Enter) is the expected continue path.
        """
        response = self._prompt(
            f"[chumicro-deploy] Fix the condition above and press "
            f"Enter to retry (attempt {attempt + 1}/"
            f"{self._max_attempts}), or type 'quit' to abort: "
        )
        normalised = response.strip().lower()
        if not normalised:
            return True
        first_char = normalised[0]
        return first_char not in ("q", "a", "e")
