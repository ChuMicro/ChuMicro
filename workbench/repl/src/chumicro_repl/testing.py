"""Test fakes for ``chumicro-repl``.

Provides three fakes for host-side tests:

- :class:`FakeSerialPort`: drop-in replacement for ``serial.Serial``
  in :class:`chumicro_repl.session.ReplSession`,
  :func:`chumicro_repl.tail`, and :func:`chumicro_repl.tui.run_loop`.
  Records writes, replays scripted reads.
- :class:`FakeKeyboard`: replays scripted keystrokes for
  :func:`chumicro_repl.tui.run_loop` tests.
- :class:`FakeTime`: deterministic seconds-domain time source that
  satisfies the ``TimeSource`` protocol so tests never sleep.
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = ["FakeKeyboard", "FakeSerialPort", "FakeTime"]


class FakeTime:
    """Deterministic seconds-domain time source for host-side tests.

    ``monotonic()`` is stable: repeated calls return the same value
    until the clock is explicitly advanced.  ``sleep()`` advances the
    clock by *duration* without a real wait.
    """

    __slots__ = ("_current",)

    def __init__(self, start: float = 0.0) -> None:
        self._current = start

    def monotonic(self) -> float:
        """Return the current fake time in seconds."""
        return self._current

    def sleep(self, duration: float) -> None:
        """Advance the clock by *duration* seconds (no wall-clock wait)."""
        self._current += duration

    def advance(self, seconds: float) -> None:
        """Move the clock forward by *seconds* without auto-sleep."""
        self._current += seconds


class FakeSerialPort:
    """In-memory replacement for :class:`serial.Serial`.

    Records every write into :attr:`writes` and replays scripted
    reads from :attr:`read_chunks`.  Each successful ``read(n)``
    consumes one chunk regardless of *n*, so tests that need to model
    fine-grained byte-level delivery should script per-byte chunks.

    Instances are callable and return themselves, so a
    ``FakeSerialPort`` instance can be passed directly as a
    ``serial_port_factory`` kwarg, with no wrapper closure needed.

    Args:
        read_chunks: Items the next ``read(n)`` call returns, in
            order.  Each item is either ``bytes`` (returned verbatim)
            or an instance of :class:`BaseException` (raised on the
            call, used to script ``OSError`` / ``SerialException``
            disconnects mid-stream).  When the script is exhausted,
            subsequent reads return ``b""`` and ``in_waiting`` is
            ``0``.
        raise_on_write: When set, the next ``write(...)`` call
            raises this exception instead of recording the data.
            Used to script disconnects that fail the host's first
            attempt to send a keystroke.
        open_error: When set, calling the instance (used as a
            factory) raises this exception.  Lets tests script
            "the factory failed to open a port" without a closure.
    """

    def __init__(
        self,
        *,
        read_chunks: Iterable[bytes | BaseException] | None = None,
        raise_on_write: BaseException | None = None,
        open_error: Exception | None = None,
    ) -> None:
        self.writes: list[bytes] = []
        self.closed = False
        self._read_chunks: list[bytes | BaseException] = list(read_chunks or [])
        self._read_index = 0
        self._raise_on_write = raise_on_write
        self._open_error = open_error

    def __call__(self, *_args: object, **_kwargs: object) -> FakeSerialPort:
        """Return this port, or raise the scripted *open_error*.

        Accepts both positional and keyword args so the same fake
        plugs into factories that use either calling convention.
        """
        if self._open_error is not None:
            raise self._open_error
        return self

    @property
    def in_waiting(self) -> int:
        """Length of the next scripted chunk, or ``0`` when exhausted.

        Scripted ``BaseException`` entries are reported as having
        ``in_waiting == 1`` so polling loops actually call
        :meth:`read` (which then raises) instead of looping past the
        scripted disconnect.
        """
        if self._read_index < len(self._read_chunks):
            entry = self._read_chunks[self._read_index]
            if isinstance(entry, BaseException):
                return 1
            return len(entry)
        return 0

    def read(self, size: int = 1) -> bytes:
        """Return the next scripted chunk verbatim, or raise.

        ``size`` is honored insofar as the chunk is no larger than
        what was scripted; tests that depend on partial chunking
        should script the chunks at the granularity they care about.
        Scripted exceptions are raised instead of returned.
        """
        if self._read_index < len(self._read_chunks):
            entry = self._read_chunks[self._read_index]
            self._read_index += 1
            if isinstance(entry, BaseException):
                raise entry
            return entry
        return b""

    def write(self, data: bytes, /) -> int:
        """Record a write, or raise the configured exception."""
        if self._raise_on_write is not None:
            raise self._raise_on_write
        self.writes.append(bytes(data))
        return len(data)

    def close(self) -> None:
        """Mark the port as closed."""
        self.closed = True

    def reset_input_buffer(self) -> None:
        """No-op, required by the :class:`SerialPort` protocol."""

    def feed(self, *chunks: bytes | BaseException) -> None:
        """Append more scripted chunks (or exceptions) after construction.

        Lets a test set up a session, exec one script, and then
        prepare the next round of bytes (or a scripted disconnect)
        without rebuilding the port.
        """
        self._read_chunks.extend(chunks)


class FakeKeyboard:
    """Scripted keyboard input for :func:`chumicro_repl.tui.run_loop`.

    Each entry in :attr:`scripted_input` is delivered as a single
    ``read_available()`` return value.  When the script is
    exhausted, subsequent calls return ``b""`` and the loop will
    eventually stall unless the test arranges another exit
    (typically by sending Ctrl-X as the last scripted entry).
    """

    def __init__(self, scripted_input: Iterable[bytes] | None = None) -> None:
        self._queued: list[bytes] = list(scripted_input or [])
        self._index = 0

    def read_available(self) -> bytes:
        """Return the next scripted byte block or ``b""`` at EOF."""
        if self._index < len(self._queued):
            entry = self._queued[self._index]
            self._index += 1
            return entry
        return b""

    def queue(self, *chunks: bytes) -> None:
        """Append more scripted chunks after construction."""
        self._queued.extend(chunks)
