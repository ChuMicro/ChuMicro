"""Stream REPL output for a bounded window.

:func:`tail` opens a serial port, reads for *seconds* of wall-clock
time, decodes bytes UTF-8 safely, writes them to *output* with ANSI
highlighting, and returns an :class:`ExitCode` describing why the
window ended.  When the device drops mid-stream, tail can hold the
window open and reopen the port on replug.

Tail does not touch the REPL mode (no Ctrl-A / Ctrl-B sent).  The
caller decides whether the board is in raw or friendly REPL before
tail runs, and what to do with the returned :class:`ExitCode`.
"""

from __future__ import annotations

import sys
import time as _time_module
from enum import Enum
from typing import TextIO, cast

from ._serial import (
    DeviceLike,
    PortFactory,
    SerialPort,
    TimeSource,
    close_quietly,
    default_port_factory,
    flush_quietly,
    read_chunk,
    resolve_address,
    write_disconnect_notice,
)
from .framing import Utf8StreamDecoder
from .highlight import DEFAULT_THEME, Theme, colorize_stream_chunk
from .patterns import PatternKind, StreamingPatternDetector


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
#: mid-stream.  30 seconds covers the typical unplug-and-replug cycle
#: without keeping a CI script hung indefinitely.  Pass
#: ``reconnect_seconds=0.0`` to disable.
DEFAULT_TAIL_RECONNECT_SECONDS = 30.0

#: Interval between reconnect attempts.  500 ms is fast enough that
#: a quick replug feels instant and slow enough that the host isn't
#: hammering the OS device-node lookup.
DEFAULT_TAIL_RECONNECT_INTERVAL = 0.5


def tail(
    device: DeviceLike | str,
    seconds: float,
    *,
    fail_on_traceback: bool = True,
    output: TextIO | None = None,
    theme: Theme | None = None,
    baudrate: int = 115200,
    time: TimeSource | None = None,
    port_factory: PortFactory | None = None,
    reconnect_seconds: float = DEFAULT_TAIL_RECONNECT_SECONDS,
    reconnect_interval: float = DEFAULT_TAIL_RECONNECT_INTERVAL,
) -> ExitCode:
    """Stream *seconds* of serial output from *device* to *output*.

    Runs until the window elapses, the caller interrupts, the device
    drops past the reconnect budget, or (when *fail_on_traceback* is
    ``True``) a noteworthy pattern is detected.  Highlighting is
    inline, so the caller sees tracebacks in red as bytes stream by.

    Args:
        device: :class:`chumicro_deploy.Device` or a serial port path
            string.  Only the address + baudrate are consulted; the
            deploy-mode fields are ignored.
        seconds: Length of the tail window.  A :class:`float` is
            accepted so sub-second tails are possible in tests.
        fail_on_traceback: When ``True`` (default), a matched
            traceback / safe-mode / hard-fault pattern ends the tail
            early and the function returns
            :attr:`ExitCode.TRACEBACK_DETECTED`.  Set ``False`` to
            run the full window regardless.
        output: Destination for the streamed text.  Defaults to
            ``sys.stdout``.  ANSI escapes are emitted whether or not
            the stream is a TTY, so pipe into
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
            :data:`DEFAULT_TAIL_RECONNECT_SECONDS` (30 s); set to ``0.0``
            to disable retries (CI-friendly fail-fast).  The window
            is *additional* to *seconds*, so time spent reconnecting
            does not count against the tail budget, since the
            user's intent is "watch for *seconds* of *output*".
        reconnect_interval: Sleep between reconnect attempts.
            Default :data:`DEFAULT_TAIL_RECONNECT_INTERVAL` (0.5 s).

    Returns:
        :class:`ExitCode` describing how the tail ended.
    """
    active_output = output if output is not None else sys.stdout
    active_theme = theme if theme is not None else DEFAULT_THEME
    # ``cast`` silences a structural-typing nit: stdlib ``time.sleep``
    # has its ``seconds`` parameter marked position-only at the C layer,
    # while the ``TimeSource`` protocol declares it as a regular keyword
    # parameter.  At runtime both call shapes work; pyright flags the
    # mismatch.
    active_time: TimeSource = (
        time if time is not None else cast(TimeSource, _time_module)
    )
    active_factory: PortFactory = (
        port_factory if port_factory is not None else default_port_factory
    )
    address, resolved_baudrate = resolve_address(device, baudrate)
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
                chunk = read_chunk(port)
            except KeyboardInterrupt:  # pragma: no cover - platform-dependent
                return ExitCode.INTERRUPTED
            except OSError as disconnect_error:
                # pyserial raises ``SerialException`` (subclass of
                # ``OSError``) when the device drops mid-read; OS-level
                # ``OSError`` shows up on raw fd reads when the device
                # node disappears.  Either way: tear down the dead
                # port, optionally reopen, and resume.
                close_quietly(port)
                if reconnect_seconds <= 0:
                    write_disconnect_notice(active_output, disconnect_error)
                    return ExitCode.DISCONNECTED
                try:
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
                except KeyboardInterrupt:
                    # Ctrl-C during the replug wait ends the tail the
                    # same way it does mid-read: a clean INTERRUPTED
                    # exit rather than a propagated KeyboardInterrupt.
                    return ExitCode.INTERRUPTED
                if reconnected is None:
                    return ExitCode.DISCONNECTED
                port = reconnected
                # Reset the streaming state, because the new port has its own
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
            highlighted = colorize_stream_chunk(
                decoded, matches, detector, theme=active_theme,
            )
            active_output.write(highlighted)
            flush_quietly(active_output)
            if fail_on_traceback and any(
                pattern_match.kind in _FAIL_PATTERN_KINDS
                for pattern_match in matches
            ):
                return ExitCode.TRACEBACK_DETECTED
    finally:
        tail_text = decoder.flush()
        if tail_text:
            active_output.write(tail_text)
            flush_quietly(active_output)
        close_quietly(port)


def _write_reconnecting_notice(output: TextIO, seconds: float) -> None:
    """Announce the start of an auto-reconnect cycle.

    Printed once per disconnect; per-attempt failures stay silent so
    the output doesn't flood while the user fumbles with the cable.
    """
    output.write(
        f"\x1b[2m*** retrying for up to {seconds:.0f}s: "
        f"plug the device back in, or press Ctrl-C to abort ***\x1b[0m\r\n"
    )
    flush_quietly(output)


def _write_reconnected_notice(output: TextIO) -> None:
    """Announce a successful auto-reconnect."""
    output.write("\x1b[2m*** reconnected ***\x1b[0m\r\n")
    flush_quietly(output)


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
    success, and a final "gave up" notice on timeout, all dim-styled
    so they don't blend into device output.

    A :class:`KeyboardInterrupt` raised during the retry wait (the
    user's Ctrl-C) propagates to the caller unswallowed; :func:`tail`
    catches it and returns :attr:`ExitCode.INTERRUPTED`.

    Args:
        output: Where to print the status notices.
        error: The :class:`OSError` that triggered the reconnect, used
            in the disconnect notice.
        factory: Port factory; each retry calls
            ``factory(address, baudrate, _POLL_INTERVAL)``.
        address / baudrate: Forwarded to the factory.
        time: Injectable time source.
        reconnect_seconds: Total budget in seconds.
        reconnect_interval: Sleep between attempts.
    """
    write_disconnect_notice(output, error)
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
    flush_quietly(output)
    return None
