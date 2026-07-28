"""Serial-port helpers shared across the REPL package.

Defines the structural protocols a serial port and time source must
satisfy, the raw-REPL control-byte constants, and a handful of
teardown helpers used on disconnect and shutdown paths.

The pyserial import is deferred to ``default_port_factory`` so
importing the package costs nothing for callers that never open a
port (``--help``, pattern detector, highlighter).  A caller that
injects its own ``SerialPort`` fake via a custom ``PortFactory``
need not install pyserial at all.
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
    satisfies this, so callers can pass a deploy-style device object
    or a bare port path without a hard dependency.
    """

    address: str


class SerialPort(Protocol):
    """Structural interface for the pyserial subset this package uses.

    Covers the operations needed for raw-REPL framing and the
    interactive TUI; fakes can satisfy it without importing pyserial.
    """

    @property
    def in_waiting(self) -> int: ...
    def read(self, size: int = 1) -> bytes: ...
    def write(self, data: bytes, /) -> int | None: ...
    def close(self) -> None: ...
    def reset_input_buffer(self) -> None: ...


class TimeSource(Protocol):
    """Structural interface for an injectable ``time`` module.

    Covers the ``monotonic()`` + ``sleep()`` subset the package uses;
    a fake satisfies it so tests need no wall-clock waits.
    """

    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


#: Factory signature: ``(address, baudrate, timeout) -> SerialPort``.
#: Exposed so callers can inject a fake without pyserial installed.
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
    import serial  # noqa: PLC0415 - deferred optional dependency

    return serial.Serial(address, baudrate=baudrate, timeout=timeout)


#: Ctrl-A: enter CircuitPython / MicroPython raw REPL.
CTRL_A = b"\x01"
#: Ctrl-B: exit raw REPL back to the friendly REPL.
CTRL_B = b"\x02"
#: Ctrl-C: KeyboardInterrupt in the friendly REPL; cancels pending
#: raw-REPL input.
CTRL_C = b"\x03"
#: Ctrl-D: terminates raw-REPL input and triggers exec; in the
#: friendly REPL, triggers a soft reboot.
CTRL_D = b"\x04"
#: Ctrl-E: enters paste mode in the friendly REPL.  Forwarded by
#: the TUI; not used by the raw-REPL helpers.
CTRL_E = b"\x05"
#: Ctrl-X: reserved by the TUI to exit without rebooting.  Never
#: forwarded to the device.
CTRL_X = b"\x18"

#: Raw-REPL prompt the board emits after Ctrl-A.
RAW_REPL_PROMPT = b"raw REPL; CTRL-B to exit\r\n>"
#: End-of-output marker inside a raw-REPL response.  The full framing
#: is ``OK<stdout>\\x04<stderr>\\x04>``: Ctrl-D separates stdout from
#: stderr, and the second Ctrl-D plus ``>`` signals that the device
#: is ready for the next input.
RAW_REPL_EOT = b"\x04"


def read_chunk(port: SerialPort) -> bytes:
    """Return whatever bytes *port* has buffered, or one polled byte.

    When ``in_waiting`` reports buffered bytes, returns the whole
    burst in one call.  Otherwise issues ``read(1)``, which blocks up
    to the port's configured timeout so a caller waiting on a marker
    does not spin on an idle link.

    ``OSError`` (typically ``serial.SerialException``) from a device
    that disappeared mid-read is allowed to propagate.  Each caller
    shapes its own disconnect response, so this helper stays
    exception-neutral.
    """
    available = port.in_waiting
    if available:
        return port.read(available)
    return port.read(1)


def close_quietly(port: SerialPort) -> None:
    """Close *port*, swallowing the OSError a dead port often raises.

    Lets teardown code run unconditionally without a dead-port close
    failure crashing the surrounding loop.
    """
    try:
        port.close()
    except OSError:  # pragma: no cover -port already dying
        pass


def flush_quietly(stream: TextIO) -> None:
    """Flush *stream*, swallowing closed-stream errors.

    Output may be a real terminal, a captured ``StringIO``, or a pipe
    that closed mid-stream; a flush failure should not propagate into
    the read loop.
    """
    try:
        stream.flush()
    except (OSError, ValueError):  # pragma: no cover -closed stream
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
    output.write(f"\r\n\x1b[2m*** device disconnected: {error} ***\x1b[0m\r\n")
    flush_quietly(output)


def resolve_address(
    device: DeviceLike | str,
    fallback_baudrate: int,
) -> tuple[str, int]:
    """Return ``(address, baudrate)`` for a device-like object or path string.

    Accepts any object with an ``address`` attribute (and optionally
    ``baudrate``) so a bare port-path caller works without a
    deploy-style device object.
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
