"""Serial-port helpers shared by :mod:`.tail`, :mod:`.session`, :mod:`.tui`.

Hides the optional ``pyserial`` import behind a function — the
package can be imported (``import chumicro_repl``) without pyserial
installed, which keeps ``--help`` and the pattern-detector /
highlighter paths light-weight for callers that never open a serial
port.

Also owns the small set of helpers that every streaming consumer
(``tail`` / ``run_loop`` / ``run_line_mode`` / ``ReplSession``) calls
on the disconnect / shutdown paths — closing a port quietly, writing
the standard disconnect notice, flushing a TextIO without crashing on
closed streams, and resolving ``(address, baudrate)`` from either a
device object exposing an ``.address`` attribute (e.g. a
``chumicro_deploy.Device``) or a bare port-path string.  Sharing the
implementations here keeps the four entry points behaviorally
consistent without three copies of each helper drifting apart.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from typing import TextIO


class DeviceLike(Protocol):
    """Structural interface for the slice of a serial device this
    package consumes.

    Any object exposing ``address`` (and optionally ``baudrate``)
    satisfies this — keeps the REPL importable and usable for
    bare-port-path callers without ``chumicro-deploy`` installed.
    ``chumicro_deploy.Device`` satisfies it via duck typing.
    """

    address: str


class SerialPort(Protocol):
    """Structural interface for the pyserial subset this package uses.

    Matches the slice of ``serial.Serial`` we rely on for raw-REPL
    framing and the interactive TUI.  Fakes in
    :mod:`chumicro_repl.testing` satisfy this protocol without
    importing pyserial.
    """

    @property
    def in_waiting(self) -> int: ...
    def read(self, size: int = 1) -> bytes: ...
    def write(self, data: bytes, /) -> int | None: ...
    def close(self) -> None: ...
    def reset_input_buffer(self) -> None: ...


class TimeSource(Protocol):
    """Structural interface for an injectable ``time`` module.

    Matches the subset of the stdlib ``time`` module the package
    uses.  :class:`~chumicro_repl.testing.FakeTime` satisfies it so
    tests eliminate wall-clock waits.
    """

    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


#: Factory signature: ``(address, baudrate, timeout) -> SerialPort``.
#: Passed through the public entry points so tests can inject a fake
#: without pyserial installed.
PortFactory = Callable[[str, int, float], SerialPort]


def default_port_factory(
    address: str,
    baudrate: int,
    timeout: float,
) -> SerialPort:
    """Open a real pyserial port.

    Imports pyserial lazily so the package stays import-light.  Any
    caller that hands a :class:`SerialPort` fake via a custom
    *port_factory* can avoid pyserial entirely.

    Args:
        address: Serial port path (``/dev/cu.usbmodem...`` on macOS,
            ``COM3`` on Windows, etc.).
        baudrate: Line rate.  115200 is the default both runtimes
            boot into.
        timeout: Per-read timeout in seconds.  Applied to every
            ``read()``; callers doing long polling pass a short
            timeout and loop.

    Returns:
        An open :class:`SerialPort`.
    """
    import serial  # noqa: PLC0415 — deferred optional dependency

    return serial.Serial(address, baudrate=baudrate, timeout=timeout)


#: Ctrl-A — enter CircuitPython / MicroPython raw REPL.
CTRL_A = b"\x01"
#: Ctrl-B — exit raw REPL back to the friendly REPL.
CTRL_B = b"\x02"
#: Ctrl-C — KeyboardInterrupt in the friendly REPL; cancels pending
#: raw-REPL input.
CTRL_C = b"\x03"
#: Ctrl-D — terminates raw-REPL input + triggers exec; in the
#: friendly REPL, triggers a soft reboot.
CTRL_D = b"\x04"
#: Ctrl-E — enters paste mode in the friendly REPL.  Forwarded by
#: the TUI; not used by the raw-REPL helpers.
CTRL_E = b"\x05"
#: Ctrl-X — reserved by the TUI to exit without rebooting.  Never
#: forwarded to the device.
CTRL_X = b"\x18"

#: Raw-REPL prompt the board emits after Ctrl-A.
RAW_REPL_PROMPT = b"raw REPL; CTRL-B to exit\r\n>"
#: End-of-output marker inside a raw-REPL response.  The framing is
#: ``OK<stdout>\\x04<stderr>\\x04>`` — Ctrl-D separates stdout from
#: stderr, and the second Ctrl-D + ``>`` signals "ready for the next
#: input".
RAW_REPL_EOT = b"\x04"


def close_quietly(port: SerialPort) -> None:
    """Close *port*, swallowing the OSError a dead port often raises.

    Reused on the disconnect / reconnect paths so the dead-port
    teardown can't itself crash the streaming loop or the
    ``ReplSession.__exit__`` path.
    """
    try:
        port.close()
    except OSError:  # pragma: no cover — port already dying
        pass


def flush_quietly(stream: TextIO) -> None:
    """Flush *stream*, swallowing closed-stream errors from tests.

    Used by every streaming surface after each render — the user's
    output may be a real terminal, a captured ``StringIO``, or a
    pipe that closed mid-tail; we never want a flush failure to
    propagate into the protocol loop.
    """
    try:
        stream.flush()
    except (OSError, ValueError):  # pragma: no cover — closed stream
        pass


def write_disconnect_notice(output: TextIO, error: OSError) -> None:
    """Write a one-line dim notice describing a disconnect to *output*.

    Kept short and ANSI-styled so it doesn't blend into device
    output the user was watching.  The exception message comes from
    pyserial / the OS, so it usually points at the actual cause
    (``[Errno 6] Device not configured`` / ``device reports
    readiness to read but returned no data`` / ``Input/output
    error``).  ``\\r\\n`` line endings render correctly under
    terminal raw mode (where the OS no longer auto-translates
    ``\\n``).
    """
    output.write(f"\r\n\x1b[2m*** device disconnected — {error} ***\x1b[0m\r\n")
    flush_quietly(output)


def resolve_address(
    device: DeviceLike | str,
    fallback_baudrate: int,
) -> tuple[str, int]:
    """Return ``(address, baudrate)`` for a device-like object or path string.

    Duck-typed — accepts any object with an ``address`` attribute
    (and optionally ``baudrate``) so callers don't pull in a hard
    ``chumicro_deploy`` import for the bare-port-path case.
    """
    if isinstance(device, str):
        return device, fallback_baudrate
    address = getattr(device, "address", None)
    if not isinstance(address, str):
        raise TypeError(
            f"expected a str port path or an object with .address, "
            f"got {type(device).__name__}"
        )
    baudrate = getattr(device, "baudrate", fallback_baudrate)
    return address, int(baudrate)
