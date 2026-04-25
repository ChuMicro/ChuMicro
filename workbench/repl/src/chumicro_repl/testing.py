"""Test fakes for ``chumicro-repl``.

Provides three fakes for host-side tests:

- :class:`FakeSerialPort` — drop-in replacement for ``serial.Serial``
  in :class:`chumicro_repl.session.ReplSession`,
  :func:`chumicro_repl.tail.tail`, and :func:`chumicro_repl.tui.run_loop`.
  Records writes, replays scripted reads.
- :class:`FakeKeyboard` — replays scripted keystrokes for
  :func:`chumicro_repl.tui.run_loop` tests.
- :class:`FakeTime` — deterministic seconds-domain time source that
  satisfies the ``TimeSource`` protocol so tests never sleep.

Mirrors the structure of :mod:`chumicro_deploy.testing` so a
contributor moving between the two packages sees the same shapes.
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = ["FakeKeyboard", "FakeSerialPort", "FakeTime"]


class FakeTime:
    """Deterministic seconds-domain time source for host-side tests.

    ``monotonic()`` is stable — repeated calls return the same value
    until the clock is explicitly advanced.  ``sleep()`` advances the
    clock by *duration* without a real wait.

    Mirrors :class:`chumicro_deploy.testing.FakeTime`.
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
    consumes one chunk regardless of *n* — tests that need to model
    fine-grained byte-level delivery should script per-byte chunks.

    Args:
        read_chunks: Bytes to return on each ``read(n)`` call, in
            order.  When the script is exhausted, subsequent reads
            return ``b""`` and ``in_waiting`` is ``0``.
    """

    def __init__(
        self,
        *,
        read_chunks: Iterable[bytes] | None = None,
    ) -> None:
        self.writes: list[bytes] = []
        self.closed = False
        self._read_chunks: list[bytes] = list(read_chunks or [])
        self._read_index = 0

    @property
    def in_waiting(self) -> int:
        """Length of the next scripted chunk, or ``0`` when exhausted."""
        if self._read_index < len(self._read_chunks):
            return len(self._read_chunks[self._read_index])
        return 0

    def read(self, size: int = 1) -> bytes:
        """Return the next scripted chunk verbatim, or ``b""`` at EOF.

        ``size`` is honored insofar as the chunk is no larger than
        what was scripted; tests that depend on partial chunking
        should script the chunks at the granularity they care about.
        """
        if self._read_index < len(self._read_chunks):
            chunk = self._read_chunks[self._read_index]
            self._read_index += 1
            return chunk
        return b""

    def write(self, data: bytes, /) -> int:
        """Record a write."""
        self.writes.append(bytes(data))
        return len(data)

    def close(self) -> None:
        """Mark the port as closed."""
        self.closed = True

    def reset_input_buffer(self) -> None:
        """No-op for the fake — a future test may want to record this call."""

    def feed(self, *chunks: bytes) -> None:
        """Append more scripted chunks after construction.

        Lets a test set up a session, exec one script, and then
        prepare the next round of bytes without rebuilding the port.
        """
        self._read_chunks.extend(chunks)


class FakeKeyboard:
    """Scripted keyboard input for :func:`chumicro_repl.tui.run_loop`.

    Each entry in :attr:`scripted_input` is delivered as a single
    ``read_available()`` return value.  When the script is
    exhausted, subsequent calls return ``b""`` — the loop will
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
