"""Per-line stdout dispatcher shared by both transports' ``execute`` path.

The transports accumulate bytes from their serial link incrementally.
:class:`StreamingLineDispatcher` turns that byte stream into newline-terminated
string dispatches to a caller-supplied ``on_line`` callback.

Optional ``prefix_bytes_to_skip`` drops a leading envelope byte count
(the raw-REPL ``OK`` acknowledgement on CircuitPython).  Optional
``terminator`` halts dispatch at the first occurrence of that byte
sequence (the ``\\x04`` end-of-stdout marker on both runtimes).
mpremote's ``data_consumer`` already scopes to the stdout segment, so
the MicroPython transport feeds bytes with ``prefix_bytes_to_skip=0``
and only relies on the terminator-strip to drop the trailing ``\\x04``
byte that mpremote forwards before exiting its read loop.
"""

from __future__ import annotations

from collections.abc import Callable


class StreamingLineDispatcher:
    """Buffer serial bytes across feeds and dispatch one string per newline.

    Each :meth:`feed` call:

    1. Drops any bytes still inside the prefix-skip window.
    2. If the chunk contains the terminator byte, truncates at it and
       latches ``terminator_seen=True`` so all later feeds become
       no-ops.  Any tail bytes before the terminator (no trailing
       ``\\n``) are dispatched as the final partial line.
    3. Buffers what remains and emits one ``on_line`` call per complete
       ``\\n``-terminated line.  Trailing bytes without a newline stay
       buffered for the next feed.

    :meth:`flush` dispatches any remaining buffered bytes as a final
    partial line.  Call once at the end of the stream when the
    terminator never arrived (idle-timeout path).

    A trailing ``\\r`` (raw REPL emits ``\\r\\n``) is stripped from each
    emitted line.  Bytes are decoded as UTF-8 with ``errors='replace'``
    so a malformed byte never crashes the host.
    """

    def __init__(
        self,
        on_line: Callable[[str], None],
        *,
        prefix_bytes_to_skip: int = 0,
        terminator: bytes = b"",
    ) -> None:
        self._on_line = on_line
        self._prefix_remaining = prefix_bytes_to_skip
        self._terminator = terminator
        self._terminator_seen = False
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> None:
        """Append bytes from the serial stream and dispatch any complete lines."""
        if self._terminator_seen or not chunk:
            return
        if self._prefix_remaining > 0:
            to_drop = min(self._prefix_remaining, len(chunk))
            self._prefix_remaining -= to_drop
            chunk = chunk[to_drop:]
            if not chunk:
                return
        if self._terminator:
            terminator_index = chunk.find(self._terminator)
            if terminator_index != -1:
                self._buffer.extend(chunk[:terminator_index])
                self._dispatch_complete_lines()
                self._dispatch_partial_tail()
                self._terminator_seen = True
                return
        self._buffer.extend(chunk)
        self._dispatch_complete_lines()

    def flush(self) -> None:
        """Dispatch any remaining buffered bytes as a final partial line.

        No-op once the terminator has been seen (the partial tail was
        already dispatched at terminator time).
        """
        if self._terminator_seen:
            return
        self._dispatch_partial_tail()

    def _dispatch_complete_lines(self) -> None:
        while True:
            newline_index = self._buffer.find(b"\n")
            if newline_index == -1:
                return
            line_bytes = bytes(self._buffer[:newline_index])
            del self._buffer[: newline_index + 1]
            if line_bytes.endswith(b"\r"):
                line_bytes = line_bytes[:-1]
            self._on_line(line_bytes.decode("utf-8", errors="replace"))

    def _dispatch_partial_tail(self) -> None:
        if not self._buffer:
            return
        tail = bytes(self._buffer)
        self._buffer.clear()
        if tail.endswith(b"\r"):
            tail = tail[:-1]
        self._on_line(tail.decode("utf-8", errors="replace"))
