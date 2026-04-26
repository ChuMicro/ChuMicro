"""``TCPClientSocket`` protocol — the surface every adapter implements.

Decision 0031 §2 names the minimum surface downstream libs touch.
Duck-typed (not an ABC) so adapters don't pay a base-class constructor
walk on creation.  Use ``isinstance(sock, TCPClientSocket)`` only
where a runtime check is genuinely needed; type-checker conformance
falls out of structural typing.

The five operations:

* ``send`` — write bytes; returns the number sent (may be < len for
  non-blocking sockets that hit a partial send).
* ``recv_into`` — read into a caller-allocated buffer.  No ``recv()``
  is exposed; CircuitPython's ``socketpool`` only ships ``recv_into``,
  so the cross-runtime API matches the most-restrictive runtime.
* ``close`` — release the underlying file descriptor / radio handle.
* ``setblocking`` / ``settimeout`` — control non-blocking behaviour;
  return values on a would-block raise ``OSError(EAGAIN=11)`` across
  all three runtimes.
* ``fileno`` — for ``select.poll().register(fd, ...)``.  Returns ``-1``
  on adapters whose socket has no real fd (CP-radio fakes); callers
  who need polling check for ``-1`` and fall back to ``settimeout``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TCPClientSocket(Protocol):
    """Minimum surface every TCP adapter implements (Decision 0031 §2).

    All four adapters (CP socketpool, MP stdlib socket, CPython stdlib
    socket, and the FakeSocket from :mod:`chumicro_sockets.testing`)
    satisfy this protocol.  Downstream libs (``chumicro-mqtt``,
    a future ``chumicro-requests``) annotate against this type
    instead of any concrete adapter.
    """

    def send(self, data: bytes) -> int:
        """Write *data* and return the number of bytes sent.

        Non-blocking sockets may return less than ``len(data)`` —
        callers must loop or buffer the unsent tail.  ``OSError``
        with ``errno == 11`` (EAGAIN) means "would block, retry";
        any other ``OSError`` is a real error.
        """

    def recv_into(self, buffer: bytearray, nbytes: int = 0) -> int:
        """Read up to *nbytes* bytes into *buffer*.

        Returns the number of bytes received (``0`` indicates a clean
        peer close).  ``nbytes=0`` reads up to ``len(buffer)`` —
        matches the stdlib ``socket.recv_into`` convention so
        downstream code that already follows it works unchanged.
        Raises ``OSError(EAGAIN=11)`` on would-block.
        """

    def close(self) -> None:
        """Release the underlying socket handle.

        Idempotent — closing an already-closed socket is a no-op.
        After ``close`` the only safe operation is another ``close``.
        """

    def setblocking(self, flag: bool) -> None:
        """Toggle blocking / non-blocking I/O.

        ``False`` switches to non-blocking; subsequent ``send`` /
        ``recv_into`` calls raise ``OSError(EAGAIN)`` instead of
        sleeping.  Equivalent to ``settimeout(None)`` for ``True``
        and ``settimeout(0.0)`` for ``False``.
        """

    def settimeout(self, seconds: float | None) -> None:
        """Set a timeout for blocking calls.

        ``None`` means block indefinitely; ``0.0`` is non-blocking;
        any positive float is a per-call deadline.  Some adapters
        coerce this to ``setblocking`` semantics — that's allowed
        as long as the protocol's "raises OSError(EAGAIN) on
        would-block" contract holds.
        """

    def fileno(self) -> int:
        """Return the integer file descriptor for ``select.poll()``.

        Returns ``-1`` for adapters whose socket has no real fd
        (CP radio fakes).  Callers that need ``poll()`` check for
        ``-1`` and degrade to ``settimeout``-based polling.
        """
