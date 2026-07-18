"""Test helpers for libraries that depend on chumicro-websockets.

Two in-memory fakes: :class:`FakeConnection` (a bidirectional pipe
satisfying the TCP client socket shape) and :class:`FakeListener` (a
stand-in for :func:`chumicro_sockets.listener`). For ticks, use
:class:`chumicro_timing.testing.FakeTicks` via the ``ticks=`` kwarg.
"""

__chumicro_test_support__ = True


import errno


class FakeConnection:
    """Bidirectional in-memory pipe modeling a TCP client socket.

    Inject into :class:`WebSocketClient` via ``transport_factory=lambda
    *_args, **_kwargs: FakeConnection()``, or hand into a
    :class:`Connection` directly. Drive the two halves with
    :meth:`feed_inbound` (bytes the local end will read) and
    :meth:`read_outbound` (drain what the local end wrote).

    The fake is non-blocking: an empty inbound buffer raises
    ``OSError(EAGAIN)``, and :meth:`close_inbound` flips that to EOF.

    Error injection:

    * ``raise_on_send`` / ``raise_on_recv``: set to an exception instance
      and the next :meth:`send` / :meth:`recv_into` raises it, then resets.
    * ``send_chunk_cap``: cap each :meth:`send` to this many bytes, for
      exercising partial-send resumption.

    ``closed`` flips ``True`` after :meth:`close`; ``outbound`` /
    ``inbound`` are the raw buffers (prefer the helper methods).
    """

    def __init__(self) -> None:
        self.outbound = bytearray()
        self.inbound = bytearray()
        self.closed = False
        self.eof = False
        self.raise_on_send = None
        self.raise_on_recv = None
        self.send_chunk_cap = None

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def feed_inbound(self, data: bytes) -> None:
        """Append *data* to the inbound queue (will be visible to recv_into)."""
        self.inbound.extend(data)

    def read_outbound(self) -> bytes:
        """Drain everything the local end has written and return it."""
        data = bytes(self.outbound)
        self.outbound = bytearray()
        return data

    def peek_outbound(self) -> bytes:
        """Return the outbound buffer without draining (non-destructive)."""
        return bytes(self.outbound)

    def close_inbound(self) -> None:
        """Signal peer-EOF: next recv_into returns 0 instead of EAGAIN."""
        self.eof = True

    # ------------------------------------------------------------------
    # TCP client socket surface
    # ------------------------------------------------------------------

    def setblocking(self, flag: bool) -> None:  # noqa: ARG002 - protocol
        """Accept the call; the fake is always non-blocking."""

    def send(self, data: bytes) -> int:
        """Append *data* to outbound; return how many bytes were "sent"."""
        if self.raise_on_send is not None:
            error_to_raise = self.raise_on_send
            self.raise_on_send = None
            raise error_to_raise
        cap = self.send_chunk_cap
        if cap is None or len(data) <= cap:
            self.outbound.extend(data)
            return len(data)
        self.outbound.extend(data[:cap])
        return cap

    def recv_into(self, buffer, nbytes: int = 0) -> int:
        """Pull up to *nbytes* (or len(buffer)) into *buffer*; EAGAIN if empty."""
        if self.raise_on_recv is not None:
            error_to_raise = self.raise_on_recv
            self.raise_on_recv = None
            raise error_to_raise
        cap = nbytes if nbytes else len(buffer)
        if not self.inbound:
            if self.eof:
                return 0
            # OSError(EAGAIN), not BlockingIOError: MicroPython lacks the
            # latter, and real adapters raise OSError on every runtime.
            raise OSError(errno.EAGAIN, "no data ready")
        take = min(cap, len(self.inbound))
        buffer[:take] = self.inbound[:take]
        # CircuitPython doesn't support `del bytearray[start:stop]`.
        # Slice-rebind works on every runtime.
        self.inbound = bytearray(self.inbound[take:])
        return take

    def close(self) -> None:
        """Mark the connection closed."""
        self.closed = True


class FakeListener:
    """Stand-in for :func:`chumicro_sockets.listener`.

    Tests call :meth:`queue_accept` to enqueue a peer connection
    that the next :meth:`accept` call returns; an empty queue
    raises ``OSError(EAGAIN)`` just like a real non-blocking listener.

    Inject into :class:`WebSocketServer` via the ``listener=``
    constructor argument.
    """

    def __init__(self) -> None:
        self._pending = []
        self.closed = False

    def queue_accept(self, peer: FakeConnection) -> None:
        """Enqueue *peer*; the next ``accept()`` call returns it."""
        self._pending.append(peer)

    def accept(self):
        """Return ``(connection, address)`` or raise EAGAIN if no pending."""
        if not self._pending:
            # OSError, not BlockingIOError, since MicroPython lacks the latter.
            raise OSError(errno.EAGAIN, "no pending connection")
        peer = self._pending.pop(0)
        return peer, ("127.0.0.1", 12345)

    def close(self) -> None:
        """Mark the listener closed."""
        self.closed = True
