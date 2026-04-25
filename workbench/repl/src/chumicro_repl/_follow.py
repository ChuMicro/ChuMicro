"""Stream REPL output for a bounded window.

The deploy pipeline wants a "push code, then watch the board for a
few seconds" primitive — :func:`tail` is that primitive.  It reads
the friendly REPL (no raw-REPL switch), decodes bytes UTF-8 safely,
writes them to *output* with ANSI highlighting, and returns an
:class:`ExitCode` that reflects why the tail ended:

- :attr:`ExitCode.OK` — the *seconds* window elapsed with no
  noteworthy patterns.
- :attr:`ExitCode.TRACEBACK_DETECTED` — a pattern match ended the
  tail early (only when *fail_on_traceback* is ``True``).
- :attr:`ExitCode.INTERRUPTED` — the caller's signal handler raised
  :class:`KeyboardInterrupt` while we were reading.

Tail operates on whatever the board emits to the serial port.  It
does not send Ctrl-A / Ctrl-B — the caller controls whether the
session is in raw REPL or friendly REPL before tail runs.
"""

from __future__ import annotations

import sys
import time as _time_module
from enum import Enum
from typing import TYPE_CHECKING, TextIO

from ._serial import (
    PortFactory,
    SerialPort,
    TimeSource,
    default_port_factory,
)
from .framing import Utf8StreamDecoder
from .highlight import DEFAULT_THEME, Theme, colorize
from .patterns import PatternKind, PatternMatch, StreamingPatternDetector

if TYPE_CHECKING:
    from chumicro_deploy import Device


class ExitCode(int, Enum):
    """Outcome of a :func:`tail` invocation.

    Int-valued so the CLI can return them directly to the shell.
    ``0`` is success; every other value is a distinct failure mode
    so the caller can differentiate "tail timed out" from "tail
    saw a traceback" in scripts.
    """

    OK = 0
    TRACEBACK_DETECTED = 1
    INTERRUPTED = 2


#: Pattern kinds that count as a "failure" for *fail_on_traceback*.
#: Soft-reboot banners are informational and do not fail a tail.
_FAIL_PATTERN_KINDS = frozenset({
    PatternKind.TRACEBACK,
    PatternKind.HARD_FAULT,
    PatternKind.SAFE_MODE,
})

#: Poll interval while waiting for new bytes.  Short enough that
#: timeouts land within ~5 ms; long enough not to peg a CPU core on
#: a quiet link.
_POLL_INTERVAL = 0.005


def tail(
    device: Device | str,
    seconds: float,
    *,
    fail_on_traceback: bool = True,
    output: TextIO | None = None,
    theme: Theme | None = None,
    baudrate: int = 115200,
    time: TimeSource | None = None,
    port_factory: PortFactory | None = None,
) -> ExitCode:
    """Stream *seconds* of serial output from *device* to *output*.

    The function opens the serial port, reads until either the
    window elapses or (when *fail_on_traceback* is ``True``) a
    noteworthy pattern is detected.  Output is decoded UTF-8 safely
    and highlighted inline — the caller sees tracebacks in red as
    they stream by, instead of waiting for the window to close.

    Args:
        device: :class:`chumicro_deploy.Device` or a serial port path
            string.  Only the address + baudrate are consulted; the
            deploy-mode fields are ignored (tail does not push code).
        seconds: Length of the tail window.  A :class:`float` is
            accepted so sub-second tails are possible in tests.
        fail_on_traceback: When ``True`` (default), a matched
            traceback / safe-mode / hard-fault pattern ends the tail
            early and the function returns
            :attr:`ExitCode.TRACEBACK_DETECTED`.  Set ``False`` to
            run the full window regardless.
        output: Destination for the streamed text.  Defaults to
            ``sys.stdout``.  ANSI escapes are emitted whether or not
            the stream is a TTY — pipe into
            :func:`chumicro_repl.highlight.strip_ansi_sequences`
            downstream for plain text.
        theme: Color theme.  Defaults to
            :data:`chumicro_repl.highlight.DEFAULT_THEME`.
        baudrate: Only consulted when *device* is a string.
        time: Injectable time source (tests).  Defaults to the stdlib
            ``time`` module.
        port_factory: Injectable port factory (tests).  Defaults to
            a real pyserial ``Serial``.

    Returns:
        :class:`ExitCode` describing how the tail ended.
    """
    active_output = output if output is not None else sys.stdout
    active_theme = theme if theme is not None else DEFAULT_THEME
    active_time: TimeSource = time if time is not None else _time_module
    active_factory: PortFactory = (
        port_factory if port_factory is not None else default_port_factory
    )
    address, resolved_baudrate = _resolve_address(device, baudrate)
    port: SerialPort = active_factory(
        address, resolved_baudrate, _POLL_INTERVAL,
    )
    decoder = Utf8StreamDecoder()
    detector = StreamingPatternDetector()
    deadline = active_time.monotonic() + seconds
    try:
        while True:
            remaining = deadline - active_time.monotonic()
            if remaining <= 0:
                return ExitCode.OK
            try:
                chunk = _read_chunk(port)
            except KeyboardInterrupt:  # pragma: no cover — platform-dependent
                return ExitCode.INTERRUPTED
            if not chunk:
                active_time.sleep(_POLL_INTERVAL)
                continue
            decoded = decoder.decode(chunk)
            if not decoded:
                continue
            matches = detector.feed(decoded)
            highlighted = _highlight_chunk(decoded, matches, detector, active_theme)
            active_output.write(highlighted)
            try:
                active_output.flush()
            except (OSError, ValueError):  # pragma: no cover — closed stream
                pass
            if fail_on_traceback and any(
                pattern_match.kind in _FAIL_PATTERN_KINDS
                for pattern_match in matches
            ):
                return ExitCode.TRACEBACK_DETECTED
    finally:
        tail_text = decoder.flush()
        if tail_text:
            active_output.write(tail_text)
            try:
                active_output.flush()
            except (OSError, ValueError):  # pragma: no cover — closed stream
                pass
        try:
            port.close()
        except OSError:  # pragma: no cover — port already closed
            pass


def _read_chunk(port: SerialPort) -> bytes:
    """Return whatever bytes the port has buffered, or a single byte.

    Prefers ``read(in_waiting)`` so a burst of output comes through
    in one call; falls back to ``read(1)`` which blocks up to the
    port's timeout so the tail does not spin on an idle link.
    """
    available = port.in_waiting
    if available:
        return port.read(available)
    return port.read(1)


def _highlight_chunk(
    text: str,
    matches: list[PatternMatch],
    detector: StreamingPatternDetector,
    theme: Theme,
) -> str:
    """Render *text* with ANSI highlighting using *matches*.

    *matches* indices are in the logical-stream coordinate system
    the :class:`~chumicro_repl.patterns.StreamingPatternDetector`
    uses — absolute offsets from the start of the stream.  This
    helper translates them to offsets within *text* using the
    detector's current offset so the ANSI wrapping lands on the
    correct substrings of the current chunk.
    """
    if not matches:
        return text
    # Translate absolute offsets back into *text* coordinates.  The
    # detector's `_offset` is the start of its internal buffer, which
    # after trim equals the start of *text* plus already-processed
    # characters.  Since this chunk was appended before we asked for
    # matches, offsets beyond ``len(text)`` cannot exist.
    stream_start = detector.total_fed - len(text)
    local_matches: list[PatternMatch] = []
    for pattern_match in matches:
        local_start = pattern_match.start - stream_start
        local_end = pattern_match.end - stream_start
        if local_end <= 0 or local_start >= len(text):
            continue
        local_start = max(0, local_start)
        local_end = min(len(text), local_end)
        local_matches.append(
            PatternMatch(
                kind=pattern_match.kind,
                start=local_start,
                end=local_end,
                text=text[local_start:local_end],
            )
        )
    return colorize(text, theme=theme, matches=local_matches)


def _resolve_address(
    device: Device | str,
    fallback_baudrate: int,
) -> tuple[str, int]:
    """Extract ``(address, baudrate)`` from a Device or a path string."""
    if isinstance(device, str):
        return device, fallback_baudrate
    address = getattr(device, "address", None)
    if not isinstance(address, str):
        raise TypeError(
            f"tail() expected a str port path or an object with "
            f".address, got {type(device).__name__}"
        )
    baudrate = getattr(device, "baudrate", fallback_baudrate)
    return address, int(baudrate)
