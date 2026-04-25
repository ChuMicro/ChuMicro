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
from typing import TYPE_CHECKING, TextIO, cast

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
    saw a traceback" from "the board got unplugged" in scripts.
    """

    OK = 0
    TRACEBACK_DETECTED = 1
    INTERRUPTED = 2
    DISCONNECTED = 3


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


#: Default reconnect window for ``tail()`` when the device drops
#: mid-stream.  30 seconds covers the typical "unplug, fumble for
#: the right cable, plug back in" cycle without keeping a CI script
#: hung indefinitely.  Pass ``reconnect_seconds=0.0`` to disable.
DEFAULT_RECONNECT_SECONDS = 30.0

#: Interval between reconnect attempts.  500 ms is fast enough that
#: a quick replug feels instant and slow enough that the host isn't
#: hammering the OS device-node lookup.
DEFAULT_RECONNECT_INTERVAL = 0.5


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
    reconnect_seconds: float = DEFAULT_RECONNECT_SECONDS,
    reconnect_interval: float = DEFAULT_RECONNECT_INTERVAL,
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
        reconnect_seconds: When the device drops mid-tail, retry
            opening the port through *port_factory* for up to this
            many seconds before giving up and returning
            :attr:`ExitCode.DISCONNECTED`.  Default
            :data:`DEFAULT_RECONNECT_SECONDS` (30 s); set to ``0.0``
            to disable retries (CI-friendly fail-fast).  The window
            is *additional* to *seconds* — time spent reconnecting
            does not count against the tail budget, since the
            user's intent is "watch for *seconds* of *output*".
        reconnect_interval: Sleep between reconnect attempts.
            Default :data:`DEFAULT_RECONNECT_INTERVAL` (0.5 s).

    Returns:
        :class:`ExitCode` describing how the tail ended.
    """
    active_output = output if output is not None else sys.stdout
    active_theme = theme if theme is not None else DEFAULT_THEME
    # ``cast`` silences a structural-typing nit: stdlib ``time.sleep``
    # has its ``seconds`` parameter marked position-only at the C layer,
    # while the ``TimeSource`` protocol declares it as a regular keyword
    # parameter.  At runtime both call shapes work; pyright flags the
    # mismatch.  Same workaround chumicro-deploy uses for its identical
    # ``TimeSource`` protocol.
    active_time: TimeSource = (
        time if time is not None else cast(TimeSource, _time_module)
    )
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
            except OSError as disconnect_error:
                # pyserial raises ``SerialException`` (subclass of
                # ``OSError``) when the device drops mid-read; OS-level
                # ``OSError`` shows up on raw fd reads when the device
                # node disappears.  Either way: tear down the dead
                # port, optionally reopen, and resume.
                _close_quietly(port)
                if reconnect_seconds <= 0:
                    _write_disconnect_notice(active_output, disconnect_error)
                    return ExitCode.DISCONNECTED
                reconnected = _attempt_reconnect(
                    output=active_output,
                    error=disconnect_error,
                    factory=active_factory,
                    address=address,
                    baudrate=resolved_baudrate,
                    time=active_time,
                    reconnect_seconds=reconnect_seconds,
                    reconnect_interval=reconnect_interval,
                )
                if reconnected is None:
                    return ExitCode.DISCONNECTED
                port = reconnected
                # Reset the streaming state — the new port has its own
                # buffer, so any pending UTF-8 partial bytes from the
                # old port are gone.  Keeping the pattern detector
                # would risk emitting a match that straddled the gap.
                decoder = Utf8StreamDecoder()
                detector = StreamingPatternDetector()
                continue
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
        _close_quietly(port)


def _read_chunk(port: SerialPort) -> bytes:
    """Return whatever bytes the port has buffered, or a single byte.

    Prefers ``read(in_waiting)`` so a burst of output comes through
    in one call; falls back to ``read(1)`` which blocks up to the
    port's timeout so the tail does not spin on an idle link.

    Raises :class:`OSError` (typically ``serial.SerialException``)
    when the device disappears mid-read — the caller catches and
    returns :attr:`ExitCode.DISCONNECTED`.
    """
    available = port.in_waiting
    if available:
        return port.read(available)
    return port.read(1)


def _write_disconnect_notice(output: TextIO, error: OSError) -> None:
    """Write a one-line dim notice describing a disconnect to *output*.

    Kept short and ANSI-styled so it doesn't blend into device
    output the user was watching.  The exception message comes
    from pyserial / the OS, so it usually points at the actual
    cause (``[Errno 6] Device not configured`` /
    ``device reports readiness to read but returned no data`` /
    ``Input/output error``).
    """
    output.write(f"\r\n\x1b[2m*** device disconnected — {error} ***\x1b[0m\r\n")
    try:
        output.flush()
    except (OSError, ValueError):  # pragma: no cover — closed stream
        pass


def _write_reconnecting_notice(output: TextIO, seconds: float) -> None:
    """Announce the start of an auto-reconnect cycle.

    Printed once per disconnect; per-attempt failures stay silent so
    the output doesn't flood while the user fumbles with the cable.
    """
    output.write(
        f"\x1b[2m*** retrying for up to {seconds:.0f}s — "
        f"plug the device back in or interrupt to abort ***\x1b[0m\r\n"
    )
    try:
        output.flush()
    except (OSError, ValueError):  # pragma: no cover — closed stream
        pass


def _write_reconnected_notice(output: TextIO) -> None:
    """Announce a successful auto-reconnect."""
    output.write("\x1b[2m*** reconnected ***\x1b[0m\r\n")
    try:
        output.flush()
    except (OSError, ValueError):  # pragma: no cover — closed stream
        pass


def _close_quietly(port: SerialPort) -> None:
    """Close *port*, swallowing the OSError a dead port often raises.

    Reused on the disconnect / reconnect paths so the dead-port
    teardown can't itself crash the loop.
    """
    try:
        port.close()
    except OSError:  # pragma: no cover — port already dying
        pass


def _attempt_reconnect(
    *,
    output: TextIO,
    error: OSError,
    factory: PortFactory,
    address: str,
    baudrate: int,
    time: TimeSource,
    reconnect_seconds: float,
    reconnect_interval: float,
) -> SerialPort | None:
    """Loop calling *factory* until it succeeds or the budget runs out.

    Returns the freshly-opened :class:`SerialPort` on success, or
    ``None`` when the reconnect budget was exhausted.  Writes a
    one-time "retrying" notice on entry, a "reconnected" notice on
    success, and a final "gave up" notice on timeout — all dim-styled
    so they don't blend into device output.

    Catches :class:`KeyboardInterrupt` from the user's signal
    handler and treats it as "stop reconnecting" — the caller's
    return path turns that into :attr:`ExitCode.INTERRUPTED`.

    Args:
        output: Where to print the status notices.
        error: The :class:`OSError` that triggered the reconnect.
            Used in the disconnect notice so the user sees what
            went wrong.
        factory: Same factory the original :func:`tail` call used.
            Each retry calls ``factory(address, baudrate,
            _POLL_INTERVAL)`` — the closure captures address and
            baudrate.
        address / baudrate: Forwarded to the factory.
        time: Injectable time source.
        reconnect_seconds: Total budget in seconds.
        reconnect_interval: Sleep between attempts.
    """
    _write_disconnect_notice(output, error)
    _write_reconnecting_notice(output, reconnect_seconds)
    deadline = time.monotonic() + reconnect_seconds
    while time.monotonic() < deadline:
        time.sleep(reconnect_interval)
        try:
            new_port = factory(address, baudrate, _POLL_INTERVAL)
        except OSError:
            continue
        _write_reconnected_notice(output)
        return new_port
    output.write(
        f"\x1b[2m*** giving up after {reconnect_seconds:.0f}s ***\x1b[0m\r\n"
    )
    try:
        output.flush()
    except (OSError, ValueError):  # pragma: no cover — closed stream
        pass
    return None


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
