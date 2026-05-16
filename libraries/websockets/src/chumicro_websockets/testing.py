"""Test helpers for libraries that depend on chumicro-websockets.

Two fakes parallel to the patterns proven in
:mod:`chumicro_sockets.testing` — fakes ship in the upstream library
so consumers don't write their own:

* :class:`FakeConnection` — bidirectional in-memory pipe satisfying
  the :class:`chumicro_sockets.TCPClientSocket` shape consumed by
  :class:`WebSocketClient` / :class:`Connection`.  Drive both sides
  via :meth:`feed_inbound` (peer pushes data the local end will
  read) + :meth:`read_outbound` (drain whatever the local end has
  written).  Inject an ``OSError`` via ``raise_on_send`` /
  ``raise_on_recv`` to exercise EAGAIN and socket-error paths.

* :class:`FakeListener` — stand-in for
  :func:`chumicro_sockets.tcp_listening_socket`.  Tests call
  :meth:`queue_accept` to enqueue a :class:`FakeConnection` that
  the next :meth:`accept` call returns; an empty queue surfaces
  EAGAIN exactly like a real non-blocking listener.

For ticks-domain fakes use :class:`chumicro_timing.testing.FakeTicks`
— pass it through the client's / server's ``ticks=`` kwarg.
"""

#: Test-support: PyPI sdist / wheel only -- bundles and product /
#: app / functional device deploys exclude it; the on-device unit
#: sweep is the one path that stages it.
__chumicro_test_support__ = True


class FakeConnection:
    """Bidirectional in-memory pipe modeling :class:`TCPClientSocket`.

    Inject into :class:`WebSocketClient` via ``connection_factory=lambda
    *_args, **_kwargs: FakeConnection()``, or hand into a
    :class:`Connection` directly.  The two halves of the pipe are
    addressable distinctly:

    * :meth:`feed_inbound` puts bytes on the peer-to-local path —
      they show up on the next :meth:`recv_into`.
    * :meth:`read_outbound` drains whatever the local end has written
      (via :meth:`send`) so test assertions can inspect the bytes.

    The fake is non-blocking: an empty inbound buffer raises
    ``OSError(EAGAIN)``.  Closing inbound via :meth:`close_inbound`
    flips the EAGAIN behavior to "EOF" so tests can simulate a
    peer disconnecting.

    Error injection:

    * ``raise_on_send`` — set to an :class:`Exception` instance and
      the next :meth:`send` raises it (then resets to ``None``).
    * ``raise_on_recv`` — same shape for :meth:`recv_into`.
    * ``send_chunk_cap`` — when set, each :meth:`send` returns at
      most this many bytes.  Useful for exercising partial-send
      resumption without injecting a full error.

    Public observation:

    * ``closed`` — flips ``True`` after :meth:`close`.
    * ``outbound`` / ``inbound`` — raw :class:`bytearray` buffers
      (read-only convention; tests should use :meth:`read_outbound`
      and :meth:`feed_inbound`).
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
        """Signal peer-EOF — next recv_into returns 0 instead of EAGAIN."""
        self.eof = True

    # ------------------------------------------------------------------
    # TCPClientSocket protocol
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
            # ``OSError(EAGAIN)`` rather than ``BlockingIOError`` —
            # MicroPython lacks the latter.  Real adapters raise
            # ``OSError`` too on every runtime, so this is closer to
            # what production sees.
            raise OSError(11, "no data ready")
        take = min(cap, len(self.inbound))
        buffer[:take] = self.inbound[:take]
        # CircuitPython doesn't support `del bytearray[start:stop]` —
        # slice-rebind works on every runtime.
        self.inbound = bytearray(self.inbound[take:])
        return take

    def close(self) -> None:
        """Mark the connection closed (idempotent)."""
        self.closed = True


class FakeListener:
    """Stand-in for :func:`chumicro_sockets.tcp_listening_socket`.

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
        """Enqueue *peer* — the next ``accept()`` call returns it."""
        self._pending.append(peer)

    def accept(self):
        """Return ``(connection, address)`` or raise EAGAIN if no pending."""
        if not self._pending:
            # OSError, not BlockingIOError — see FakeConnection.recv_into above.
            raise OSError(11, "no pending connection")
        peer = self._pending.pop(0)
        return peer, ("127.0.0.1", 12345)

    def close(self) -> None:
        """Mark the listener closed (idempotent)."""
        self.closed = True
