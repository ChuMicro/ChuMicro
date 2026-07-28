"""Interactive REPL TUI: forwards stdin ↔ serial with highlighting.

The TUI is deliberately thin: stdin bytes are passed through to the
board unchanged, serial bytes are UTF-8 decoded and ANSI-highlighted
before being written to stdout.  The board does its own line
editing: arrow keys, backspace, paste-mode (Ctrl-E) all reach the
device verbatim.

Keybindings mirror ``mpremote repl``:

- **Ctrl-C**: forwarded to the board.  Raises
  :class:`KeyboardInterrupt` on-device, which cancels whatever is
  running and returns to the friendly REPL.
- **Ctrl-D**: forwarded to the board.  Soft-reboots the runtime
  (MicroPython prints ``MPY: soft reboot``, CircuitPython is
  silent but rewinds).
- **Ctrl-E**: forwarded to the board.  Enters MicroPython paste
  mode; CircuitPython ignores it.
- **Ctrl-X**: intercepted locally.  Exits the TUI without
  rebooting or interrupting the board.

The loop is structured so tests can drive it without real terminal
machinery: :func:`run_loop` takes injectable input / output / port /
time dependencies; :func:`interactive` is the thin wrapper that
opens a real pyserial port and puts stdin into raw mode.
"""

from __future__ import annotations

import contextlib
import sys
import time as _time_module
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, BinaryIO, Protocol, TextIO, cast

from ._follow import ExitCode
from ._serial import (
    CTRL_X,
    DeviceLike,
    PortFactory,
    SerialPort,
    TimeSource,
    close_quietly,
    default_port_factory,
    flush_quietly,
    resolve_address,
    write_disconnect_notice,
)
from .framing import Utf8StreamDecoder
from .highlight import DEFAULT_THEME, Theme, colorize_stream_chunk
from .patterns import StreamingPatternDetector

if TYPE_CHECKING:
    from pathlib import Path


#: Poll interval inside the interactive loop.  Short enough to keep
#: key echo feeling instantaneous; long enough not to peg a CPU.
_POLL_INTERVAL = 0.005

#: Wall-clock ceiling on the on-exit serial drain.  After Ctrl-X the
#: loop keeps reading so the user sees the board's final output; a
#: board stuck in a tight ``print`` loop would otherwise stream
#: forever and Ctrl-X would never return.  The deadline caps the flush
#: so Ctrl-X exits promptly no matter what the board is doing.
_EXIT_DRAIN_SECONDS = 1.5


class KeyInputReader(Protocol):
    """Structural interface for a non-blocking keyboard source.

    The POSIX adapter reads from a termios raw-mode fd; the test
    fake replays scripted byte sequences.  Both must expose a
    non-blocking ``read_available`` so the interactive loop never
    stalls waiting for input.
    """

    def read_available(self) -> bytes:
        """Return every byte currently buffered, or ``b""`` if none."""
        ...


def run_loop(
    port: SerialPort,
    keyboard: KeyInputReader,
    output: TextIO,
    *,
    time: TimeSource | None = None,
    theme: Theme | None = None,
    exit_key: bytes = CTRL_X,
    welcome_banner: str = "",
    initial_send: bytes = b"",
    reopen: Callable[[], SerialPort] | None = None,
    reconnect_seconds: float = 0.0,
    reconnect_interval: float = 0.5,
) -> int:
    """Run the interactive I/O loop until *exit_key* is pressed.

    Returns ``0`` on a normal Ctrl-X exit, or
    :attr:`ExitCode.DISCONNECTED` (``3``) when the device drops and
    no reconnect callback is supplied (or the reconnect budget is
    exhausted).  Callers driving the loop from tests can inject
    custom *keyboard* / *output* / *time* to validate the
    forward-and-highlight behavior without a real serial port.

    Args:
        port: Open :class:`SerialPort`.  The TUI writes keystrokes
            and reads device output through this port.  Closing the
            port remains the caller's responsibility.
        keyboard: Non-blocking keystroke source.
        output: Destination for serial output.  ANSI escapes are
            written whether or not the stream is a TTY; the caller
            owns the decision to strip them downstream.
        time: Injectable time source.
        theme: Color theme for pattern highlighting.
        exit_key: Byte sequence that ends the loop without being
            forwarded to the device.  Defaults to Ctrl-X.
        welcome_banner: Local text written to *output* before the
            loop starts.  Used by :func:`interactive` to introduce
            the connection (transport, address, keybinding hints);
            tests pass an empty string to keep output deterministic.
        initial_send: Bytes written to the port before the loop
            starts.  Defaults to empty; :func:`interactive` sends a
            single carriage return so the friendly REPL reprints
            its ``>>>`` prompt instead of staring at a blank line.
        reopen: Callable returning a fresh :class:`SerialPort`,
            invoked when the current port drops and
            *reconnect_seconds* allows.  Defaults to ``None`` (no
            auto-reconnect, so the loop returns
            :attr:`ExitCode.DISCONNECTED` on the first disconnect).
            :func:`interactive` wires this to a closure over the
            original port factory so a replug picks up
            automatically.
        reconnect_seconds: Reconnect budget per disconnect, in
            seconds.  ``0.0`` (default) means no retry; positive
            values loop *reopen* until success or budget exhausted.
            Ctrl-X during reconnect aborts immediately.
        reconnect_interval: Sleep between reconnect attempts.
    """
    # ``cast`` silences a structural-typing nit on stdlib ``time``;
    # see the matching note in :mod:`chumicro_repl.session`.
    active_time: TimeSource = (
        time if time is not None else cast(TimeSource, _time_module)
    )
    active_theme = theme if theme is not None else DEFAULT_THEME
    decoder = Utf8StreamDecoder()
    detector = StreamingPatternDetector()
    if welcome_banner:
        output.write(welcome_banner)
        flush_quietly(output)

    def _try_recover(
        error: OSError,
        *,
        send_initial_after: bool,
    ) -> int | tuple[SerialPort, Utf8StreamDecoder, StreamingPatternDetector]:
        """Run the reconnect loop after *error* and prepare fresh state.

        Returns either:
          * An ``int`` exit code: the caller must return it from
            :func:`run_loop` immediately (``0`` on user-requested exit
            during reconnect, :attr:`ExitCode.DISCONNECTED` on budget
            exhaustion).
          * A ``(port, decoder, detector)`` tuple: the caller swaps
            its locals for these fresh instances and continues the
            loop.

        When *send_initial_after* is true and *initial_send* is non-
        empty, the helper writes *initial_send* to the new port so
        the friendly REPL reprints its ``>>>`` after the reconnect.
        Pass ``False`` from the initial-send branch (where the caller
        is about to retry the initial write itself).
        """
        new_port, user_exited = _tui_reconnect(
            error=error,
            output=output,
            keyboard=keyboard,
            exit_key=exit_key,
            reopen=reopen,
            time=active_time,
            reconnect_seconds=reconnect_seconds,
            reconnect_interval=reconnect_interval,
            old_port=port,
        )
        if user_exited:
            return 0
        if new_port is None:
            return int(ExitCode.DISCONNECTED)
        if send_initial_after and initial_send:
            try:
                new_port.write(initial_send)
            except OSError:  # pragma: no cover -replug-then-replug
                pass
        return new_port, Utf8StreamDecoder(), StreamingPatternDetector()
    if initial_send:
        try:
            port.write(initial_send)
        except OSError as initial_error:
            outcome = _try_recover(initial_error, send_initial_after=False)
            if isinstance(outcome, int):
                return outcome
            port, decoder, detector = outcome
            try:
                port.write(initial_send)
            except OSError:  # pragma: no cover -replug-then-replug
                pass
    while True:
        exit_requested = False
        key_bytes = keyboard.read_available()
        if key_bytes:
            if exit_key in key_bytes:
                prefix = key_bytes.split(exit_key, 1)[0]
                if prefix:
                    try:
                        port.write(prefix)
                    except OSError:  # pragma: no cover -exiting anyway
                        pass
                exit_requested = True
            else:
                try:
                    port.write(key_bytes)
                except OSError as write_error:
                    outcome = _try_recover(write_error, send_initial_after=True)
                    if isinstance(outcome, int):
                        return outcome
                    port, decoder, detector = outcome
                    continue
        # Drain serial output before honoring an exit request, so the
        # user sees whatever the board printed in response to the last
        # keystroke before the TUI vanishes.  On exit the drain loops
        # until ``in_waiting`` reports zero or the exit-drain deadline
        # elapses.  The deadline keeps Ctrl-X responsive against a board
        # printing in a tight loop, where ``in_waiting`` never settles.
        had_serial_activity = False
        exit_drain_deadline = (
            active_time.monotonic() + _EXIT_DRAIN_SECONDS
            if exit_requested
            else 0.0
        )
        while True:
            if exit_requested and active_time.monotonic() >= exit_drain_deadline:
                break
            try:
                available = port.in_waiting
                if not available:
                    break
                chunk = port.read(available)
            except OSError as read_error:
                outcome = _try_recover(read_error, send_initial_after=True)
                if isinstance(outcome, int):
                    return outcome
                port, decoder, detector = outcome
                break
            had_serial_activity = True
            decoded = decoder.decode(chunk)
            if decoded:
                matches = detector.feed(decoded)
                output.write(colorize_stream_chunk(
                    decoded, matches, detector, theme=active_theme,
                ))
                flush_quietly(output)
            if not exit_requested:
                # Return to the keyboard-poll loop after one drain
                # so interactive typing stays responsive; we only
                # loop the drain when the user has asked to exit.
                break
        if exit_requested:
            return 0
        if not had_serial_activity and not key_bytes:
            active_time.sleep(_POLL_INTERVAL)


#: Default reconnect window for the interactive TUI when the
#: device drops mid-session.  Long enough to cover a fumbled
#: replug; bounded so a forgotten session eventually exits
#: instead of holding the terminal hostage.  Press Ctrl-X
#: during the window to abort early.  Named to distinguish from
#: the shorter tail() default in :mod:`._follow`; the two
#: surfaces want different ceilings (a CI-tail wants to fail
#: fast; an interactive session wants to wait for the user).
DEFAULT_TUI_RECONNECT_SECONDS = 60.0


def interactive(
    device: DeviceLike | str,
    *,
    baudrate: int = 115200,
    input_stream: BinaryIO | None = None,
    output: TextIO | None = None,
    theme: Theme | None = None,
    time: TimeSource | None = None,
    port_factory: PortFactory | None = None,
    raw_mode_context: Callable[[int], contextlib.AbstractContextManager[None]] | None = None,
    reconnect_seconds: float = DEFAULT_TUI_RECONNECT_SECONDS,
    reconnect_interval: float = 0.5,
) -> int:
    """Open *device* and run the interactive TUI until Ctrl-X.

    Thin wrapper over :func:`run_loop`.  Pulls in the POSIX
    terminal raw-mode setup, the real pyserial port factory, and
    the default stdin/stdout streams.  Tests that want to drive the
    loop deterministically should call :func:`run_loop` directly
    with a fake :class:`KeyInputReader` and :class:`SerialPort`.

    Args:
        device: :class:`chumicro_deploy.Device` or a serial path.
        baudrate: Consulted when *device* is a string.
        input_stream: Binary stdin.  Defaults to ``sys.stdin.buffer``.
        output: Text output.  Defaults to ``sys.stdout``.
        theme: Color theme.
        time: Injectable time source.
        port_factory: Injectable port factory.
        raw_mode_context: Callable yielding a terminal raw-mode
            context manager for a given fd.  Defaults to
            :func:`_posix_raw_mode`; tests pass a no-op.
        reconnect_seconds: How long to keep retrying the port
            factory after the device drops mid-session.  Default
            :data:`DEFAULT_TUI_RECONNECT_SECONDS` (60 s); pass ``0.0``
            to disable reconnect (the loop returns
            :attr:`ExitCode.DISCONNECTED` on the first OSError).
            Press Ctrl-X during the retry window to abort
            immediately.
        reconnect_interval: Sleep between reconnect attempts.

    Returns:
        ``0`` on normal Ctrl-X exit (including Ctrl-X during a
        reconnect window); :attr:`ExitCode.DISCONNECTED` (``3``)
        when the device drops and the reconnect budget runs out.
    """
    active_input: BinaryIO = (
        input_stream if input_stream is not None else sys.stdin.buffer
    )
    active_output = output if output is not None else sys.stdout
    active_factory: PortFactory = (
        port_factory if port_factory is not None else default_port_factory
    )
    raw_mode = raw_mode_context if raw_mode_context is not None else _posix_raw_mode
    address, resolved_baudrate = resolve_address(device, baudrate)
    transport_label = _transport_label(device)
    welcome_banner = _format_welcome_banner(
        address=address, baudrate=resolved_baudrate, transport=transport_label,
    )
    port = active_factory(address, resolved_baudrate, _POLL_INTERVAL)

    def reopen() -> SerialPort:
        return active_factory(address, resolved_baudrate, _POLL_INTERVAL)

    try:
        fd = _fileno_or_none(active_input)
        keyboard = _StdinKeyboard(active_input, fd)
        if fd is None:
            # Non-TTY input (test harness, piped script): skip raw-mode setup.
            return run_loop(
                port, keyboard, active_output,
                time=time, theme=theme,
                welcome_banner=welcome_banner,
                initial_send=b"\r",
                reopen=reopen,
                reconnect_seconds=reconnect_seconds,
                reconnect_interval=reconnect_interval,
            )
        with raw_mode(fd):
            return run_loop(
                port, keyboard, active_output,
                time=time, theme=theme,
                welcome_banner=welcome_banner,
                initial_send=b"\r",
                reopen=reopen,
                reconnect_seconds=reconnect_seconds,
                reconnect_interval=reconnect_interval,
            )
    finally:
        close_quietly(port)


def interactive_line(
    device: DeviceLike | str,
    *,
    baudrate: int = 115200,
    output: TextIO | None = None,
    theme: Theme | None = None,
    time: TimeSource | None = None,
    port_factory: PortFactory | None = None,
    history_root: object | None = None,
) -> int:
    """Open *device* and run the line-mode REPL.

    Sibling of :func:`interactive`.  Instead of forwarding keystrokes
    byte-by-byte to the device, it runs a host-side `prompt_toolkit`
    line editor with persistent per-device history.
    Each completed line ships to the device; serial output streams
    back through the same pattern-detector + traceback highlighter
    the passthrough TUI uses.

    Falls through to the same port factory / device-resolution shape
    as :func:`interactive`; the only delta is the input loop.

    Args:
        device: :class:`chumicro_deploy.Device` or a serial path.
        baudrate: Consulted when *device* is a string.
        output: Text output.  Defaults to ``sys.stdout``.
        theme: Color theme.
        time: Injectable time source (for the per-line drain).
        port_factory: Injectable port factory.
        history_root: Override the persistent-history root
            directory.  ``None`` (default) uses
            :data:`chumicro_repl.line_mode.DEFAULT_HISTORY_ROOT`.

    Returns:
        ``0`` on a clean exit (``:quit`` / Ctrl-D / Ctrl-C at the
        empty prompt).
    """
    from .line_mode import (  # noqa: PLC0415
        format_line_mode_banner,
        run_line_mode,
    )

    active_output = output if output is not None else sys.stdout
    active_factory: PortFactory = (
        port_factory if port_factory is not None else default_port_factory
    )
    address, resolved_baudrate = resolve_address(device, baudrate)
    port = active_factory(address, resolved_baudrate, _POLL_INTERVAL)
    try:
        return run_line_mode(
            port,
            output=active_output,
            address=address,
            history_root=cast("Path | None", history_root),
            welcome_banner=format_line_mode_banner(address=address),
            theme=theme,
            time=time,
        )
    finally:
        close_quietly(port)


def _format_welcome_banner(
    *,
    address: str,
    baudrate: int,
    transport: str | None,
) -> str:
    """Build the dim-styled startup banner shown before the REPL loop.

    Two lines, ANSI-dim, terminated with ``\\r\\n`` so the banner
    renders correctly under terminal raw mode (where the OS no
    longer auto-translates ``\\n`` to ``\\r\\n``).  Includes the
    transport when known so the user sees which runtime they're
    talking to; falls back to address-only when *device* was
    constructed from a bare port path.

    The keybinding line documents only the keys the TUI actually
    cares about: Ctrl-X is the local exit, the rest are forwarded
    verbatim and listed for discoverability rather than because the
    TUI special-cases them.
    """
    if transport:
        identity = (
            f"chumicro-repl · {address} · {transport} · {baudrate} baud"
        )
    else:
        identity = f"chumicro-repl · {address} · {baudrate} baud"
    keys = (
        "Keys: Ctrl-X exit · Ctrl-C interrupt · "
        "Ctrl-D soft-reboot · Ctrl-E paste mode"
    )
    return f"\x1b[2m{identity}\r\n{keys}\x1b[0m\r\n"


def _transport_label(device: DeviceLike | str) -> str | None:
    """Return the device's runtime label, or ``None`` for a bare path.

    Accepts any object with a ``.transport`` attribute (including the
    :class:`chumicro_deploy.Device` dataclass), so this module doesn't
    hard-depend on chumicro-deploy.
    """
    if isinstance(device, str):
        return None
    transport = getattr(device, "transport", None)
    return transport if isinstance(transport, str) else None


class _StdinKeyboard:
    """Adapter that wraps a binary input stream for :class:`KeyInputReader`.

    POSIX: in terminal raw mode, ``sys.stdin.buffer.read1(n)`` reads
    whatever is currently buffered (never blocks) once we have put
    the tty into cbreak + no-echo.  On non-TTY streams (tests /
    pipelines) we fall back to :func:`os.read` on the underlying
    file descriptor when available.
    """

    __slots__ = ("_stream", "_fd")

    def __init__(self, stream: BinaryIO, fd: int | None) -> None:
        self._stream = stream
        self._fd = fd

    def read_available(self) -> bytes:
        # ``BinaryIO`` doesn't statically expose ``read1`` (only the
        # subclass ``BufferedIOBase`` does), so the type checker can't
        # see the call.  Probe at runtime: every BufferedReader and
        # BytesIO this adapter is asked to handle has it.  Falls back
        # to a blocking ``read(n)`` on rare streams without ``read1``.
        read1: object | None = getattr(self._stream, "read1", None)
        if self._fd is None:
            if callable(read1):
                return cast(bytes, read1(256))
            return b""
        import select  # noqa: PLC0415 - stdlib-only, defer to keep imports lean

        ready, _, _ = select.select([self._fd], [], [], 0)
        if not ready:
            return b""
        if callable(read1):
            return cast(bytes, read1(256))
        return self._stream.read(256)


@contextlib.contextmanager
def _posix_raw_mode(fd: int) -> Iterator[None]:
    """Put terminal *fd* into raw mode, restore settings on exit.

    Uses :mod:`termios` / :mod:`tty`, standard library only, no
    extra deps.  On platforms without :mod:`termios` (Windows) the
    call falls through as a no-op; the TUI still works but key
    repeats and Ctrl-char interception depend on the terminal
    emulator's own behavior.
    """
    try:
        import termios  # noqa: PLC0415 - POSIX-only, deferred
        import tty  # noqa: PLC0415 - POSIX-only, deferred
    except ImportError:  # pragma: no cover -Windows path
        yield
        return
    original = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)


def _fileno_or_none(stream: BinaryIO) -> int | None:
    """Return ``stream.fileno()`` when the stream is a real fd, else ``None``.

    Tests that pass an ``io.BytesIO`` get ``None`` so the caller
    skips terminal raw-mode setup.
    """
    fileno_method = getattr(stream, "fileno", None)
    if fileno_method is None:
        return None
    try:
        return fileno_method()
    except (OSError, ValueError):
        return None


def _tui_reconnect(
    *,
    error: OSError,
    output: TextIO,
    keyboard: KeyInputReader,
    exit_key: bytes,
    reopen: Callable[[], SerialPort] | None,
    time: TimeSource,
    reconnect_seconds: float,
    reconnect_interval: float,
    old_port: SerialPort,
) -> tuple[SerialPort | None, bool]:
    """Run the reconnect loop after a disconnect.

    Returns ``(port, user_exited)``:

    * ``(new_port, False)``: factory succeeded; *new_port* is the
      live :class:`SerialPort`.
    * ``(None, True)``: the user pressed *exit_key* during the
      retry window; the caller should return ``0``.
    * ``(None, False)``: *reopen* was ``None``, the budget was
      zero, or the budget elapsed; the caller should return
      :attr:`ExitCode.DISCONNECTED`.

    Writes a "*** device disconnected: ... ***" notice on entry.
    When *reopen* is supplied and *reconnect_seconds* is positive,
    follows up with a "*** retrying ***" notice and polls until
    either the factory succeeds or the user presses *exit_key*; on
    success a "*** reconnected ***" notice fires.

    The dead *old_port* is closed quietly before any retries; the
    OS often raises another OSError on close after a hot-unplug,
    which would otherwise mask the original error.
    """
    write_disconnect_notice(output, error)
    close_quietly(old_port)
    if reopen is None or reconnect_seconds <= 0:
        return None, False
    output.write(
        f"\x1b[2m*** retrying for up to {reconnect_seconds:.0f}s: "
        f"plug the device back in, or press Ctrl-X to abort"
        f" ***\x1b[0m\r\n"
    )
    flush_quietly(output)
    deadline = time.monotonic() + reconnect_seconds
    while time.monotonic() < deadline:
        keystrokes = keyboard.read_available()
        if keystrokes and exit_key in keystrokes:
            return None, True
        time.sleep(reconnect_interval)
        try:
            new_port = reopen()
        except OSError:
            continue
        output.write("\x1b[2m*** reconnected ***\x1b[0m\r\n")
        flush_quietly(output)
        return new_port, False
    output.write(
        f"\x1b[2m*** giving up after {reconnect_seconds:.0f}s ***\x1b[0m\r\n"
    )
    flush_quietly(output)
    return None, False
