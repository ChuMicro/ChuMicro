"""``TCPClientSocket`` protocol — the surface every adapter implements.

Duck-typed: enforced by convention, not an ABC walk.  Resolves to
``typing.Protocol`` on CPython for static-type-checker conformance;
falls back to a plain class on MP / CP when ``typing`` is absent so
the import doesn't trip.

The six operations:

* ``send`` — write bytes; returns the number sent (may be < len for
  non-blocking sockets that hit a partial send).
* ``recv_into`` — read into a caller-allocated buffer.  No ``recv()``
  is exposed; CircuitPython's ``socketpool`` only ships ``recv_into``,
  so the cross-runtime API matches the most-restrictive runtime.
* ``close`` — release the underlying file descriptor / radio handle.
* ``setblocking`` / ``settimeout`` — control non-blocking behavior;
  return values on a would-block raise ``OSError(EAGAIN=11)`` across
  all three runtimes.
* ``fileno`` — for ``select.poll().register(fd, ...)``.  Returns ``-1``
  on adapters whose socket has no real fd (CP-radio fakes); callers
  who need polling check for ``-1`` and fall back to ``settimeout``.

Custom-factory sockets must follow the same would-block shape —
:func:`chumicro_sockets.is_eagain` is the consumer-side check.
"""

# ``typing.Protocol`` only exists on CPython (and CP/MP builds that
# include the optional ``typing`` stub).  Guard the import so the
# library loads on every runtime; downstream code that does
# ``isinstance(sock, TCPClientSocket)`` only runs on CPython.
try:
    from typing import Protocol, runtime_checkable  # type: ignore[import]
except ImportError:  # pragma: no cover — MP / CP without typing stub
    class Protocol:  # type: ignore[no-redef]
        """Minimal ``typing.Protocol`` stand-in for runtimes without ``typing``."""

    def runtime_checkable(cls):  # type: ignore[no-redef]
        """No-op decorator stand-in for runtimes without ``typing.runtime_checkable``."""
        return cls


@runtime_checkable
class UDPSocket(Protocol):
    """Minimum surface every UDP adapter implements.

    Datagram-oriented: ``sendto`` carries the destination on every
    call; ``recvfrom_into`` returns ``(nbytes, (host, port))`` so the
    caller can identify the sender for protocols that need it
    (NTP, mDNS, SSDP, ad-hoc replies).

    Satisfied by CP socketpool, MP stdlib socket, CPython stdlib
    socket, and ``FakeUDPSocket`` (:mod:`chumicro_sockets.testing`)
    via per-runtime wrappers in :mod:`chumicro_sockets._adapters`.
    """

    def sendto(self, data: bytes, host: str, port: int) -> int:
        """Send *data* as one datagram to ``(host, port)``.

        Returns the number of bytes accepted by the kernel — usually
        equal to ``len(data)``.  Datagrams larger than the path MTU
        are typically rejected with ``OSError(EMSGSIZE)``.  Pass IPv4
        dotted-quad strings or hostnames that resolve to one;
        adapters delegate name resolution to the runtime.
        """
        ...

    def recvfrom_into(self, buffer: bytearray, nbytes: int = 0) -> tuple:
        """Receive one datagram into *buffer*.

        Returns ``(nbytes_received, (sender_host, sender_port))``.
        Returns ``(0, (host, port))`` only when *buffer* is empty —
        UDP has no peer-close semantics.  Datagrams larger than
        *nbytes* (or ``len(buffer)`` when ``nbytes=0``) are
        **truncated**; the unread tail is discarded.

        Raises ``OSError(EAGAIN=11)`` when no datagram is queued and
        the socket is non-blocking.
        """
        ...

    def close(self) -> None:
        """Release the underlying socket handle.  Idempotent."""
        ...

    def setblocking(self, flag: bool) -> None:
        """Toggle blocking / non-blocking I/O.  Same semantics as TCP."""
        ...

    def settimeout(self, seconds) -> None:
        """Set a timeout for blocking calls.  Same semantics as TCP."""
        ...

    def fileno(self) -> int:
        """Return the integer fd or ``-1`` if the adapter has no real fd."""
        ...

    def getsockname(self) -> tuple:
        """Return the locally-bound ``(host, port)`` tuple.

        Useful when the socket was bound with ``port=0`` to obtain
        an ephemeral port the OS picked.
        """
        ...


@runtime_checkable
class TCPClientSocket(Protocol):
    """Minimum surface every TCP adapter implements.

    Satisfied by CP socketpool, MP stdlib socket, CPython stdlib
    socket, and ``FakeSocket`` (:mod:`chumicro_sockets.testing`).
    Downstream libs annotate against this type, not concrete adapters.
    """

    def send(self, data: bytes) -> int:
        """Write *data* and return the number of bytes sent.

        Non-blocking sockets may return less than ``len(data)`` —
        callers must loop or buffer the unsent tail.  ``OSError``
        with ``errno == 11`` (EAGAIN) means "would block, retry";
        any other ``OSError`` is a real error.
        """
        ...

    def recv_into(self, buffer: bytearray, nbytes: int = 0) -> int:
        """Read up to *nbytes* bytes into *buffer*.

        Returns the number of bytes received (``0`` indicates a clean
        peer close).  ``nbytes=0`` reads up to ``len(buffer)`` —
        matches the stdlib ``socket.recv_into`` convention so
        downstream code that already follows it works unchanged.
        Raises ``OSError(EAGAIN=11)`` on would-block.
        """
        ...

    def close(self) -> None:
        """Release the underlying socket handle.

        Idempotent — closing an already-closed socket is a no-op.
        After ``close`` the only safe operation is another ``close``.
        """
        ...

    def setblocking(self, flag: bool) -> None:
        """Toggle blocking / non-blocking I/O.

        ``False`` switches to non-blocking; subsequent ``send`` /
        ``recv_into`` calls raise ``OSError(EAGAIN)`` instead of
        sleeping.  Equivalent to ``settimeout(None)`` for ``True``
        and ``settimeout(0.0)`` for ``False``.
        """
        ...

    def settimeout(self, seconds) -> None:
        """Set a timeout for blocking calls.

        ``None`` means block indefinitely; ``0.0`` is non-blocking;
        any positive float is a per-call deadline.  Some adapters
        coerce this to ``setblocking`` semantics — that's allowed
        as long as the protocol's "raises OSError(EAGAIN) on
        would-block" contract holds.
        """
        ...

    def fileno(self) -> int:
        """Return the integer file descriptor for ``select.poll()``.

        Returns ``-1`` for adapters whose socket has no real fd
        (CP radio fakes).  Callers that need ``poll()`` check for
        ``-1`` and degrade to ``settimeout``-based polling.
        """
        ...
