"""Programmatic REPL session: raw REPL over pyserial.

:class:`ReplSession` is a context manager that opens a serial
connection to a CircuitPython or MicroPython board, drives the raw
REPL (Ctrl-A entry, Ctrl-D exec, ``OK<stdout>\\x04<stderr>\\x04>``
framing), and exposes three primitives:

- :meth:`~ReplSession.exec`: run a block of code, return stdout.
- :meth:`~ReplSession.call`: call a named function with literal
  arguments, return the parsed ``repr`` of the result.
- :meth:`~ReplSession.read_until`: read raw bytes until a pattern
  matches, for callers that bypass raw REPL entirely (tailing the
  friendly REPL, for instance).

The raw-REPL framing is identical between CircuitPython and
MicroPython (neither runtime adds a runtime-specific header to
either the prompt or the response), so a single code path handles
both.  The only divergence is what a soft-reboot (Ctrl-D in the
*friendly* REPL) prints: MicroPython emits ``MPY: soft reboot``,
CircuitPython is silent.  :meth:`ReplSession.exec` never exits raw
REPL, so that divergence never surfaces here; it is a concern for
the :func:`~chumicro_repl.tail` path and the interactive TUI.
"""

from __future__ import annotations

import ast
import re
import time as _time_module
from types import TracebackType
from typing import cast

from ._serial import (
    CTRL_A,
    CTRL_B,
    CTRL_C,
    CTRL_D,
    RAW_REPL_EOT,
    RAW_REPL_PROMPT,
    DeviceLike,
    PortFactory,
    SerialPort,
    TimeSource,
    default_port_factory,
    read_chunk,
    resolve_address,
)
from .framing import Utf8StreamDecoder

#: Default per-exec timeout.
DEFAULT_TIMEOUT = 10.0

#: Pause between handshake steps: after each Ctrl-C to give the
#: board time to settle, and after Ctrl-A to let the raw-REPL
#: banner fully emit before we read for the prompt.
_HANDSHAKE_SETTLE = 0.1

#: Poll interval inside :meth:`ReplSession.read_until` /
#: :meth:`_read_until_bytes`.  Kept short enough that short-timeout
#: probes feel responsive without pegging a CPU core.
_POLL_INTERVAL = 0.005

#: Char-count lookback in :meth:`ReplSession.read_until`'s
#: incremental rescan.  Each iteration searches from
#: ``last_scanned - this`` so a regex pattern straddling the
#: previous / current decode boundary still matches without
#: forcing a re-scan from offset 0 on every poll.  256 is
#: comfortably larger than any realistic REPL marker.
_READ_UNTIL_LOOKBACK = 256


class ReplSessionError(Exception):
    """Raised when a raw-REPL operation fails.

    Covers four broad classes:

    - Timeout: the board did not respond within the per-op timeout.
    - Protocol error: the board emitted bytes that don't match the
      raw-REPL framing (typically because it was not in raw REPL;
      e.g. bootloader mode, a firmware-less chip, wrong baudrate).
    - Execution error: the board executed the code but raised an
      exception.  The exception's stderr is attached as :attr:`stderr`.
    - **Disconnect**: the device dropped mid-call.  Surfaced as the
      :class:`ReplSessionDisconnected` subclass so callers can catch
      "the cable came out" without conflating it with the other
      three classes.
    """

    def __init__(self, message: str, *, stderr: str = "") -> None:
        super().__init__(message)
        #: The raw-REPL stderr block, populated when the failure was
        #: an execution error.  Empty string for timeouts / protocol
        #: errors.
        self.stderr = stderr


class ReplSessionDisconnected(ReplSessionError):
    """Raised when the underlying serial port drops mid-call.

    Subclass of :class:`ReplSessionError` so callers that catch the
    base class still get the failure, while callers that want to
    differentiate "device unplugged" from "device returned a
    traceback" can ``except ReplSessionDisconnected`` directly.

    The original :class:`OSError` (typically a
    ``serial.SerialException``) is attached as :attr:`cause` for
    callers that want the underlying errno or message.
    """

    def __init__(self, cause: OSError) -> None:
        super().__init__(f"device disconnected: {cause}")
        #: The underlying OS-level error from pyserial.
        self.cause = cause


class ReplSession:
    """Raw-REPL session over pyserial.

    Use as a context manager::

        with ReplSession(device) as session:
            output = session.exec("print(1 + 2)")
            value = session.call("os.uname")

    The constructor opens the serial port, interrupts whatever was
    running, and enters raw REPL.  The ``__exit__`` path sends Ctrl-B
    (exit raw REPL) and closes the port, so the board is left in the
    friendly REPL, ready for an interactive user or another session.

    Args:
        device: Either an object exposing ``.address`` (e.g. a
            ``chumicro_deploy.Device``) or a bare serial-port path
            string.  A bare string is treated as the ``address``;
            baudrate / time / port-factory come from the other
            keyword arguments.
        baudrate: Only consulted when *device* is a string.  Ignored
            when *device* exposes its own ``baudrate`` attribute,
            because the device's value wins.
        time: Injectable time source (for tests).  Defaults to the
            stdlib ``time`` module.
        port_factory: Injectable port factory (for tests).  Defaults
            to :func:`chumicro_repl._serial.default_port_factory`,
            which constructs a real pyserial ``Serial``.
        connect_timeout: Upper bound in seconds for the initial
            raw-REPL handshake.  Covers the Ctrl-C + Ctrl-A +
            prompt-read sequence, not the per-exec timeout.
    """

    def __init__(
        self,
        device: DeviceLike | str,
        *,
        baudrate: int = 115200,
        time: TimeSource | None = None,
        port_factory: PortFactory | None = None,
        connect_timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        address, resolved_baudrate = resolve_address(device, baudrate)
        self._address = address
        self._baudrate = resolved_baudrate
        # ``cast`` silences a structural-typing nit: stdlib ``time.sleep``
        # has its ``seconds`` parameter marked position-only at the C
        # layer, while ``TimeSource`` declares it as a regular keyword
        # parameter.  Both call shapes work at runtime; pyright flags
        # the mismatch.
        self._time: TimeSource = (
            time if time is not None else cast(TimeSource, _time_module)
        )
        self._port_factory: PortFactory = (
            port_factory if port_factory is not None else default_port_factory
        )
        self._connect_timeout = connect_timeout
        self._port: SerialPort | None = None
        self._in_raw_repl = False
        #: Bytes the port emitted past a previous marker.  Reused on
        #: the next ``_read_until_bytes`` so multi-step framing
        #: (``OK`` -> ``\x04`` -> ``\x04`` -> ``>``) doesn't drop the
        #: bytes that arrived in the same chunk as the previous
        #: marker.
        self._read_remainder = bytearray()

    def __enter__(self) -> ReplSession:
        self._port = self._port_factory(
            self._address, self._baudrate, _POLL_INTERVAL,
        )
        try:
            self._enter_raw_repl()
        except BaseException:
            # Any failure during handshake closes the port so the
            # caller doesn't leak a file descriptor.
            self._close_port()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        port = self._port
        if port is None:
            return
        if self._in_raw_repl:
            try:
                port.write(CTRL_B)
            except OSError:  # pragma: no cover -closed port during exit
                pass
        self._in_raw_repl = False
        self._close_port()

    # ------------------------------------------------------------------
    # Public raw-REPL primitives
    # ------------------------------------------------------------------

    def exec(  # noqa: A003, CHU001 - matches the upstream mpremote / upyr / pyboard API
        self,
        code: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> str:
        """Execute *code* on the board and return stdout.

        Sends *code* terminated by Ctrl-D, then reads the response
        until the second ``\\x04`` marker.  The response format is::

            OK<stdout>\\x04<stderr>\\x04>

        Returns *stdout* as a UTF-8 string.  If *stderr* is non-empty
        the call raises :class:`ReplSessionError` with ``stderr``
        attached.  Raw REPL never raises an exception object on the
        host side, only on the board, so surfacing it as a stderr
        blob is the closest host-side analog.

        Args:
            code: Python source to execute.  May contain newlines.
            timeout: Per-exec deadline in seconds.
        """
        port = self._require_port()
        code_bytes = code.encode("utf-8")
        try:
            port.write(code_bytes)
            port.write(CTRL_D)
        except OSError as disconnect_error:
            raise ReplSessionDisconnected(disconnect_error) from disconnect_error
        ok_marker = self._read_until_bytes(b"OK", timeout=timeout, port=port)
        if not ok_marker.endswith(b"OK"):
            raise ReplSessionError(
                f"raw REPL did not acknowledge exec "
                f"(got {ok_marker!r} before timeout)"
            )
        first_eot = self._read_until_bytes(
            RAW_REPL_EOT, timeout=timeout, port=port,
        )
        stdout_bytes = first_eot[:-1]
        second_eot = self._read_until_bytes(
            RAW_REPL_EOT, timeout=timeout, port=port,
        )
        stderr_bytes = second_eot[:-1]
        # The trailing ``>`` signals the board is ready for the next
        # input.  We read-and-discard it so the next exec starts from
        # a clean buffer.
        self._read_until_bytes(b">", timeout=timeout, port=port)
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if stderr:
            raise ReplSessionError(
                f"raw REPL exec returned stderr: {stderr.rstrip()}",
                stderr=stderr,
            )
        return stdout

    def call(
        self,
        function_name: str,
        *args: object,
        timeout: float = DEFAULT_TIMEOUT,
        **kwargs: object,
    ) -> object:
        """Call *function_name* on the board with literal arguments.

        Builds a one-line ``print(repr(<function_name>(*args, **kwargs)))``
        and execs it, then parses the stdout via
        :func:`ast.literal_eval`.  Round-trips anything
        :func:`literal_eval` handles: numbers, strings, bytes,
        tuples, lists, dicts, sets, booleans, ``None``.  Anything
        else raises :class:`ReplSessionError` because the repr is
        not a literal.

        Args:
            function_name: Fully-qualified dotted name.  The board
                must already have the name bound, so import whatever
                the caller needs in a prior :meth:`exec`.
            *args: Positional arguments.  Rendered via :func:`repr`.
            timeout: Per-call deadline in seconds.
            **kwargs: Keyword arguments.  Rendered via :func:`repr`.

        Returns:
            The parsed return value.  ``None`` round-trips as
            ``None``.
        """
        rendered_args = [repr(arg) for arg in args]
        rendered_kwargs = [
            f"{key}={value!r}" for key, value in kwargs.items()
        ]
        combined_arguments = ", ".join([*rendered_args, *rendered_kwargs])
        source = (
            f"print(repr({function_name}({combined_arguments})))"
        )
        stdout = self.exec(source, timeout=timeout)
        rendered = stdout.rstrip("\r\n")
        try:
            return ast.literal_eval(rendered)
        except (ValueError, SyntaxError) as error:
            raise ReplSessionError(
                f"ReplSession.call({function_name!r}) return value is not a "
                f"literal: {rendered!r}"
            ) from error

    def read_until(
        self,
        pattern: str | re.Pattern[str],
        *,
        timeout: float,
    ) -> str:
        """Read bytes until *pattern* matches the accumulated string.

        Unlike :meth:`exec` + :meth:`call`, this primitive operates
        on raw bytes from the port.  It does not send anything, and
        it accepts output produced by either the friendly or the raw
        REPL.  Callers that want to stream output from a board that
        is not under raw-REPL control (for instance, tailing a deploy)
        use this.

        Args:
            pattern: Regex (compiled or string).  The returned text
                includes the match.
            timeout: Deadline in seconds.

        Returns:
            The accumulated text up to and including the match.

        Raises:
            ReplSessionError: Timeout elapsed before the pattern matched.
        """
        port = self._require_port()
        compiled = (
            pattern if isinstance(pattern, re.Pattern)
            else re.compile(pattern)
        )
        deadline = self._time.monotonic() + timeout
        # Stream-decode incrementally so a long no-match run doesn't
        # re-decode the full accumulated buffer on every iteration.
        # ``_read_remainder`` carries bytes past a previous match
        # forward; feeding them through the decoder handles a
        # codepoint that was split at that boundary.
        decoder = Utf8StreamDecoder()
        accumulated = decoder.decode(bytes(self._read_remainder))
        self._read_remainder.clear()
        # Re-scan baseline.  Each loop searches from
        # ``last_scanned - _READ_UNTIL_LOOKBACK`` so a pattern
        # straddling the previous / current decode boundary still
        # matches without re-scanning from offset 0.
        last_scanned = 0
        while True:
            match = compiled.search(
                accumulated, max(0, last_scanned - _READ_UNTIL_LOOKBACK),
            )
            if match is not None:
                consumed_text = accumulated[:match.end()]
                tail_text = accumulated[match.end():]
                # Carry forward the decoded tail past the match plus the
                # bytes ``decoder`` is still holding for an incomplete
                # trailing code point, so a multibyte character split at
                # the match boundary survives into the next call instead
                # of decoding to U+FFFD once its continuation bytes land.
                if tail_text:
                    self._read_remainder.extend(tail_text.encode("utf-8"))
                self._read_remainder.extend(decoder.pending())
                return consumed_text
            last_scanned = len(accumulated)
            try:
                chunk = read_chunk(port)
            except OSError as disconnect_error:
                raise ReplSessionDisconnected(disconnect_error) from disconnect_error
            if chunk:
                accumulated += decoder.decode(chunk)
                continue
            if self._time.monotonic() >= deadline:
                raise ReplSessionError(
                    f"read_until({pattern!r}) timed out after "
                    f"{timeout:.3f}s; captured {accumulated!r}"
                )
            self._time.sleep(_POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _enter_raw_repl(self) -> None:
        """Interrupt the board and enter raw REPL.

        Two Ctrl-Cs to cancel anything running, then Ctrl-A to drop
        into raw REPL.  Waits for the raw-REPL banner and prompt.
        """
        port = self._require_port()
        try:
            port.reset_input_buffer()
            port.write(CTRL_C)
            self._time.sleep(_HANDSHAKE_SETTLE)
            port.write(CTRL_C)
            self._time.sleep(_HANDSHAKE_SETTLE)
            port.write(CTRL_A)
        except OSError as disconnect_error:
            raise ReplSessionDisconnected(disconnect_error) from disconnect_error
        self._time.sleep(_HANDSHAKE_SETTLE)
        prompt = self._read_until_bytes(
            RAW_REPL_PROMPT, timeout=self._connect_timeout, port=port,
        )
        if not prompt.endswith(RAW_REPL_PROMPT):
            raise ReplSessionError(
                f"raw REPL did not announce itself; got {prompt!r}"
            )
        self._in_raw_repl = True

    def _read_until_bytes(
        self,
        marker: bytes,
        *,
        timeout: float,
        port: SerialPort,
    ) -> bytes:
        """Read bytes from *port* until *marker* appears.

        Returns the accumulated bytes up to and including *marker*.
        Bytes that arrived past the marker are saved to
        :attr:`_read_remainder` and prepended to the next call so
        the framed multi-step protocol (``OK`` ``\\x04`` ``\\x04``
        ``>``) does not drop bytes when two markers land in the
        same serial-port read.

        Raises :class:`ReplSessionError` on timeout.  The
        accumulated bytes are included in the message so callers
        debugging a stuck board can see what the device sent.
        """
        deadline = self._time.monotonic() + timeout
        accumulated = bytearray(self._read_remainder)
        self._read_remainder.clear()
        while True:
            if marker in accumulated:
                marker_position = accumulated.index(marker)
                end_index = marker_position + len(marker)
                self._read_remainder.extend(accumulated[end_index:])
                return bytes(accumulated[:end_index])
            try:
                chunk = read_chunk(port)
            except OSError as disconnect_error:
                raise ReplSessionDisconnected(disconnect_error) from disconnect_error
            if chunk:
                accumulated.extend(chunk)
                continue
            if self._time.monotonic() >= deadline:
                raise ReplSessionError(
                    f"read timed out waiting for {marker!r} after "
                    f"{timeout:.3f}s; got {bytes(accumulated)!r}"
                )
            self._time.sleep(_POLL_INTERVAL)

    def _require_port(self) -> SerialPort:
        if self._port is None:
            raise ReplSessionError(
                "ReplSession used outside of 'with' block: "
                "enter the context manager before calling exec/call/read_until"
            )
        return self._port

    def _close_port(self) -> None:
        port = self._port
        self._port = None
        if port is None:
            return
        try:
            port.close()
        except OSError:  # pragma: no cover -port already closed
            pass
