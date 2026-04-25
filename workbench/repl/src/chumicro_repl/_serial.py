"""Serial-port helpers shared by :mod:`.tail`, :mod:`.session`, :mod:`.tui`.

Hides the optional ``pyserial`` import behind a function — the
package can be imported (``import chumicro_repl``) without pyserial
installed, which keeps ``--help`` and the pattern-detector /
highlighter paths light-weight for callers that never open a serial
port.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


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
