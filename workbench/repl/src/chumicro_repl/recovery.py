"""Classifies ``chumicro-repl`` session-start failures and coaches the user through a fix.

A bad cable, a held port, a missing ``dialout`` membership, or a
board stuck in unresponsive user code all surface as ``OSError`` or
:class:`ReplSessionError` when a caller opens a :class:`ReplSession`.
This module maps those exceptions to a small enum of recognized
failure kinds, pairs each kind with a :class:`RecoveryPlan` of
ordered physical steps the user can take, and offers a coaching
loop that prints the plan and retries the session start.

Public surface:

- :class:`ReplFailureKind`: enum of session-start failure modes.
- :class:`RecoveryPlan`: headline + ordered fix-steps for one kind.
- :func:`classify_session_failure`: map a session-start exception
  to a :class:`ReplFailureKind`.
- :func:`recovery_plan_for`: look up the plan registered for a kind.
- :func:`coached_session_start`: reusable classify-render-retry
  loop around any zero-arg session-opening callable.
- :class:`InteractiveReplSession`: context manager that applies
  the coaching loop around a :class:`ReplSession`.

Mid-session disconnects do not route through this module.  The
auto-reconnect loop in :func:`chumicro_repl.tail` and
:func:`chumicro_repl.tui.run_loop` handles the "device was open and
then dropped" case; this module only addresses the "it never opened
in the first place" failures.
"""

from __future__ import annotations

import errno
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import TypeVar

from ._serial import DeviceLike, PortFactory, TimeSource
from .session import (
    DEFAULT_TIMEOUT,
    ReplSession,
    ReplSessionDisconnected,
    ReplSessionError,
)

_T = TypeVar("_T")


#: Default ceiling on retry attempts.
_DEFAULT_MAX_ATTEMPTS = 3


class ReplFailureKind(Enum):
    """Classification of session-start failures.

    Each kind has a :class:`RecoveryPlan` keyed in
    :data:`_PLANS`; :func:`recovery_plan_for` is the typed accessor.
    """

    #: Port path does not exist (errno ENOENT).  Typically the
    #: board isn't plugged in, the cable is bad, or the path is
    #: wrong.
    PORT_NOT_FOUND = "port_not_found"

    #: Port path exists but another process holds it (errno EBUSY).
    #: Typically mpremote, screen, the Mu editor, or the Arduino IDE
    #: still has it open.
    PORT_BUSY = "port_busy"

    #: Port path exists and is free, but the user lacks permission
    #: to open it (errno EACCES).  Typically a Linux ``dialout``
    #: group issue.
    PORT_PERMISSION_DENIED = "port_permission_denied"

    #: Port opened successfully, but the board didn't respond to the
    #: raw-REPL handshake.  The device may be hung in tight code
    #: that ignores Ctrl-C, in safe mode, or running firmware that
    #: doesn't speak the raw-REPL protocol.
    RAW_REPL_UNRESPONSIVE = "raw_repl_unresponsive"

    #: Catch-all for failures the classifier doesn't recognize.
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

#: Substrings that mean "no such port" across pyserial / OS variations.
#: pyserial wraps the OSError but preserves the errno phrasing in the
#: message, so substring matching is reliable across
#: macOS / Linux / Windows reports.
_NOT_FOUND_PATTERNS = (
    "no such file or directory",
    "could not open port",  # typical pyserial wrapper when path missing
    "filenotfounderror",
)

_BUSY_PATTERNS = (
    "resource busy",
    "device or resource busy",
    "device busy",
    "in use",
)

_PERMISSION_PATTERNS = (
    "permission denied",
    "access is denied",
)

_UNRESPONSIVE_PATTERNS = (
    "raw repl did not announce itself",
    "did not respond",
    "read timed out waiting",
)


def classify_session_failure(error: Exception) -> ReplFailureKind:
    """Classify a session-start exception into a :class:`ReplFailureKind`.

    Recognized inputs:

    - :class:`OSError` (including :class:`serial.SerialException`,
      which subclasses :class:`OSError` in modern pyserial).  The
      classifier inspects ``errno`` first, then falls back to
      substring matching on the message, because pyserial sometimes
      wraps the OS error and re-formats the message, so neither
      alone is reliable.
    - :class:`ReplSessionDisconnected`: the device dropped during
      the handshake write.  Treated as :attr:`PORT_NOT_FOUND`
      because the user-facing fix is the same ("plug the device
      in and retry").
    - :class:`ReplSessionError`: the handshake completed without a
      raw-REPL prompt response.  Mapped to
      :attr:`RAW_REPL_UNRESPONSIVE`.
    - Anything else maps to :attr:`UNKNOWN`.

    Args:
        error: The exception caught from
            :meth:`ReplSession.__enter__` (or its inner
            ``port_factory`` call).

    Returns:
        The matching :class:`ReplFailureKind`.
    """
    # Disconnected during handshake counts as "not plugged in".
    if isinstance(error, ReplSessionDisconnected):
        return ReplFailureKind.PORT_NOT_FOUND

    # ReplSessionError (non-disconnect) means an unresponsive raw REPL.
    if isinstance(error, ReplSessionError):
        message = str(error).lower()
        for pattern in _UNRESPONSIVE_PATTERNS:
            if pattern in message:
                return ReplFailureKind.RAW_REPL_UNRESPONSIVE
        return ReplFailureKind.UNKNOWN

    # OSError family (pyserial.SerialException subclasses OSError).
    if isinstance(error, OSError):
        if error.errno == errno.ENOENT:
            return ReplFailureKind.PORT_NOT_FOUND
        if error.errno == errno.EBUSY:
            return ReplFailureKind.PORT_BUSY
        if error.errno == errno.EACCES:
            return ReplFailureKind.PORT_PERMISSION_DENIED
        message = str(error).lower()
        for pattern in _PERMISSION_PATTERNS:
            if pattern in message:
                return ReplFailureKind.PORT_PERMISSION_DENIED
        for pattern in _BUSY_PATTERNS:
            if pattern in message:
                return ReplFailureKind.PORT_BUSY
        for pattern in _NOT_FOUND_PATTERNS:
            if pattern in message:
                return ReplFailureKind.PORT_NOT_FOUND
        return ReplFailureKind.UNKNOWN

    return ReplFailureKind.UNKNOWN


# ---------------------------------------------------------------------------
# Recovery plans
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecoveryPlan:
    """User-facing guidance for a single :class:`ReplFailureKind`.

    Attributes:
        headline: One-line summary the user reads first.
        fix_steps: Ordered physical actions the user can take.
            Rendered as a bulleted list by
            :class:`InteractiveReplSession`.
    """

    headline: str
    fix_steps: tuple[str, ...]


_PLANS: dict[ReplFailureKind, RecoveryPlan] = {
    ReplFailureKind.PORT_NOT_FOUND: RecoveryPlan(
        headline="The serial port path does not exist.",
        fix_steps=(
            "Confirm the board is plugged into USB.",
            "Check the address is right: `ls /dev/cu.*` (macOS) or "
            "`ls /dev/ttyACM* /dev/ttyUSB*` (Linux) lists the "
            "current ports.",
            "If the cable is suspect, swap to a known-good data "
            "cable (charge-only cables don't enumerate the port).",
            "Tap the board's RESET button and wait 2–3 seconds for "
            "USB re-enumeration.",
        ),
    ),
    ReplFailureKind.PORT_BUSY: RecoveryPlan(
        headline="The serial port is held by another process.",
        fix_steps=(
            "Close any other tool that may have the port open: "
            "Mu, Thonny, the Arduino IDE, screen / minicom, "
            "another mpremote, PyCharm or VS Code serial console.",
            "On macOS / Linux, `lsof <port>` shows the holding "
            "process; kill it or quit the app and retry.",
            "If the port was held by a crashed process, unplug + "
            "replug the board to force the OS to release it.",
        ),
    ),
    ReplFailureKind.PORT_PERMISSION_DENIED: RecoveryPlan(
        headline="You don't have permission to open the serial port.",
        fix_steps=(
            "Linux: add yourself to the `dialout` group, then log "
            "out and back in: "
            "`sudo usermod -a -G dialout $USER`.",
            "macOS: this is rare; check ownership with "
            "`ls -l <port>`.  If the device is owned by `root`, "
            "unplug + replug to reset to your user.",
            "If running inside a container, ensure the device "
            "node is mounted into the container with the right "
            "permissions.",
        ),
    ),
    ReplFailureKind.RAW_REPL_UNRESPONSIVE: RecoveryPlan(
        headline="The board didn't respond to the raw-REPL handshake.",
        fix_steps=(
            "Tap the board's RESET button and wait a second for "
            "the runtime to come back up.",
            "If CircuitPython dropped into safe mode, press any "
            "key over a serial terminal to exit safe mode, then "
            "retry.",
            "If the board is stuck in user code that ignores "
            "Ctrl-C (e.g., a `while True: pass` with no yields), "
            "hold RESET for 2 seconds or unplug + replug the USB "
            "cable.",
            "If the board has no MicroPython / CircuitPython "
            "firmware on it, flash one with "
            "`chumicro-deploy flash-firmware` first.",
        ),
    ),
    ReplFailureKind.UNKNOWN: RecoveryPlan(
        headline="The session-start failure didn't match a known kind.",
        fix_steps=(
            "Check the underlying exception above for clues.",
            "Retry: transient USB hiccups sometimes clear on "
            "their own.",
            "If the failure repeats, file a chumicro-repl issue "
            "with the exception message and platform details.",
        ),
    ),
}


def recovery_plan_for(kind: ReplFailureKind) -> RecoveryPlan:
    """Return the :class:`RecoveryPlan` registered for *kind*.

    Every member of :class:`ReplFailureKind` has an entry; the
    function is total.
    """
    return _PLANS[kind]


# ---------------------------------------------------------------------------
# Reusable coaching loop
# ---------------------------------------------------------------------------


_ABORT_RESPONSES = frozenset({"q", "quit", "abort", "exit"})


def coached_session_start(
    factory: Callable[[], _T],
    *,
    output: Callable[[str], None] = print,
    prompt: Callable[[str], str] = input,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> _T:
    """Run *factory* with classify-coach-retry on session-start failures.

    Wraps any zero-arg callable that may raise :class:`OSError`,
    :class:`ReplSessionDisconnected`, or :class:`ReplSessionError`
    on its connect step.  On a recognized failure:

    1. :func:`classify_session_failure` maps the exception to a
       :class:`ReplFailureKind`.
    2. The matching :class:`RecoveryPlan` (headline + bulleted
       fix-steps) renders to *output*.
    3. *prompt* asks whether to retry; an abort response (``q`` /
       ``quit`` / ``abort`` / ``exit``) re-raises the last error.
       Empty / whitespace-only retries.
    4. After *max_attempts* attempts, the last error re-raises.

    Used by:

    * :class:`InteractiveReplSession`, which wraps a
      :class:`ReplSession` context manager around the coaching loop
      so programmatic callers get the same retry behavior.
    * The workspace ``repl`` CLI, which wraps the
      :func:`~chumicro_repl.tui.interactive_line` /
      :func:`~chumicro_repl.tui.interactive` calls so port-busy /
      port-not-found / permission-denied errors get the
      user-friendly coaching prompt instead of a bare traceback.

    Args:
        factory: Zero-arg callable performing the session start.
            Returns any value on success (caller's choice: could
            be a :class:`ReplSession`, an int exit code, ``None``,
            etc.); raises on connect failure.
        output: Sink for plan rendering.  Defaults to :func:`print`.
        prompt: Asks the user to retry vs abort.  Defaults to
            :func:`input`.
        max_attempts: Ceiling on retry attempts.  Defaults to 3.
            Must be ``>= 1``.

    Returns:
        Whatever *factory* returns on a successful attempt.

    Raises:
        ValueError: ``max_attempts < 1``.
        Exception: The last classified error after retries are
            exhausted or the user aborts.
    """
    if max_attempts < 1:
        raise ValueError(
            f"max_attempts must be >= 1, got {max_attempts}"
        )
    attempt = 0
    last_error: Exception | None = None
    while attempt < max_attempts:
        attempt += 1
        try:
            return factory()
        except (OSError, ReplSessionError) as error:
            last_error = error
            kind = classify_session_failure(error)
            plan = recovery_plan_for(kind)
            _render_plan(
                output=output,
                attempt=attempt,
                max_attempts=max_attempts,
                error=error,
                plan=plan,
            )
            if attempt >= max_attempts:
                raise
            if not _ask_retry(
                prompt=prompt,
                attempt=attempt,
                max_attempts=max_attempts,
            ):
                raise
            continue
    # Unreachable in practice: the except branch always raises
    # once attempts are exhausted.  Deterministic fallback for the
    # type checker.
    assert last_error is not None
    raise last_error  # pragma: no cover


def _render_plan(
    *,
    output: Callable[[str], None],
    attempt: int,
    max_attempts: int,
    error: Exception,
    plan: RecoveryPlan,
) -> None:
    """Print the recovery plan via *output*."""
    output("")
    output(
        f"Attempt {attempt}/{max_attempts} failed: "
        f"{type(error).__name__}"
    )
    output(f"  {error}")
    output("")
    output(plan.headline)
    for step in plan.fix_steps:
        output(f"  • {step}")


def _ask_retry(
    *,
    prompt: Callable[[str], str],
    attempt: int,
    max_attempts: int,
) -> bool:
    """Prompt the user; return ``False`` if they asked to abort."""
    remaining = max_attempts - attempt
    suffix = (
        f"  ({remaining} retr{'y' if remaining == 1 else 'ies'} "
        f"remaining; type 'q' to abort) "
    )
    response = prompt(
        f"\nFix the condition above and press Enter to retry…{suffix}"
    ).strip().lower()
    return response not in _ABORT_RESPONSES


# ---------------------------------------------------------------------------
# Interactive session wrapper
# ---------------------------------------------------------------------------


class InteractiveReplSession:
    """:class:`ReplSession` wrapper that coaches the user through start failures.

    On a session-start failure, classifies the exception, prints
    the matching :class:`RecoveryPlan` to *output*, prompts the
    user to fix the condition + press Enter to retry, and tries
    again, up to *max_attempts* times.

    Use as a context manager that yields a live :class:`ReplSession`::

        from chumicro_repl import InteractiveReplSession

        with InteractiveReplSession(device) as session:
            session.exec("print('hello')")

    Mid-session disconnects (after the handshake completed) do NOT
    route through this wrapper; those are handled by the
    auto-reconnect loop in :func:`tail` and :func:`run_loop`.

    Args:
        device: An object exposing ``.address`` (e.g. a
            ``chumicro_deploy.Device``) or a bare serial-port path
            string.  Forwarded to :class:`ReplSession` on each
            attempt.
        max_attempts: Ceiling on retry attempts.  Defaults to 3.
            Must be ``>= 1``.
        prompt: Injectable prompt callable.  Defaults to
            :func:`input`.  An empty / whitespace-only response
            continues with a retry; ``"q"`` / ``"quit"`` /
            ``"abort"`` / ``"exit"`` re-raises the last error
            without retrying.
        output: Injectable output sink.  Defaults to :func:`print`.
            Tests inject a list-append to make assertions.
        baudrate: Forwarded to :class:`ReplSession` when *device*
            is a string.
        time: Forwarded to :class:`ReplSession`.
        port_factory: Forwarded to :class:`ReplSession`.
        connect_timeout: Forwarded to :class:`ReplSession`.

    Raises:
        ValueError: ``max_attempts < 1``.
    """

    def __init__(
        self,
        device: DeviceLike | str,
        *,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        prompt: Callable[[str], str] = input,
        output: Callable[[str], None] = print,
        baudrate: int = 115200,
        time: TimeSource | None = None,
        port_factory: PortFactory | None = None,
        connect_timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if max_attempts < 1:
            raise ValueError(
                f"max_attempts must be >= 1, got {max_attempts}"
            )
        self._device = device
        self._max_attempts = max_attempts
        self._prompt = prompt
        self._output = output
        self._session_kwargs: dict[str, object] = {
            "baudrate": baudrate,
            "time": time,
            "port_factory": port_factory,
            "connect_timeout": connect_timeout,
        }
        self._inner: ReplSession | None = None

    def __enter__(self) -> ReplSession:
        def open_session() -> ReplSession:
            session = ReplSession(self._device, **self._session_kwargs)  # type: ignore[arg-type]
            session.__enter__()
            return session

        session = coached_session_start(
            open_session,
            output=self._output,
            prompt=self._prompt,
            max_attempts=self._max_attempts,
        )
        self._inner = session
        return session

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._inner is not None:
            self._inner.__exit__(exc_type, exc_val, exc_tb)
            self._inner = None
