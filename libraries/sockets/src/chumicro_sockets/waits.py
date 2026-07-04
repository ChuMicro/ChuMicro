"""The socket I/O wait vocabulary: ``ReadWait`` + ``WriteWait``.

Opt-in submodule — import explicitly::

    from chumicro_sockets.waits import ReadWait, WriteWait

A generator doing non-blocking socket I/O yields one of these on
``EAGAIN`` so a tick-based scheduler learns which poll direction to wait
on before it resumes the generator.  The scheduler reads a small
duck-typed wait protocol off whatever a generator yields — no named base
class, every hook optional:

* ``io_socket``: the pollable to register with ``select.poll``, or
  ``None`` to register nothing.
* ``io_interest(now_ms) -> int``: bitmask of poll directions to register
  the socket for — read, write, or both.  The bit values match
  ``chumicro_runner.IO_READ`` / ``IO_WRITE`` by value; a socket wait
  reports its single direction.
* ``next_deadline(now_ms) -> int | None``: an absolute ``ticks_ms`` tick
  at which the scheduler should resume even if the socket never becomes
  ready, or ``None`` to park indefinitely on the poll.
* ``ready(now_ms) -> bool``: optional predicate for a non-socket
  completion wait (a callback firing); a socket wait omits it.

``ReadWait`` and ``WriteWait`` each carry one socket, report one poll
direction, and take an optional absolute deadline.  They live in
``chumicro-sockets`` rather than a scheduler package because they carry a
socket and this library takes no runtime dependency (bring-your-own
scheduler): a socket must never import the loop that drives it, so the
markers sit on the socket side of that edge.

Both markers are re-yieldable: build one before an ``EAGAIN`` loop and
yield the same instance every spin, so a steady loop allocates nothing.
"""

from chumicro_sockets._connector import _IO_READ, _IO_WRITE


class ReadWait:
    """Wait for *sock* to become readable, optionally bounded by a deadline.

    Reports ``IO_READ`` interest and carries *sock* for the scheduler to
    register.  ``deadline_ms`` is an absolute ``ticks_ms`` tick the
    scheduler wakes at even if no bytes arrive; ``None`` waits on the
    poll indefinitely.  Re-yieldable across an ``EAGAIN`` recv loop.
    """

    def __init__(self, sock: object, deadline_ms: int | None = None) -> None:
        self.io_socket = sock
        self._deadline_ms = deadline_ms

    def io_interest(self, now_ms: int) -> int:  # noqa: ARG002 (wait protocol)
        return _IO_READ

    def next_deadline(self, now_ms: int) -> int | None:  # noqa: ARG002 (wait protocol)
        return self._deadline_ms


class WriteWait:
    """Wait for *sock* to become writable, optionally bounded by a deadline.

    Reports ``IO_WRITE`` interest and carries *sock* for the scheduler to
    register.  ``deadline_ms`` is an absolute ``ticks_ms`` tick the
    scheduler wakes at even if the socket never drains; ``None`` waits on
    the poll indefinitely.  Re-yieldable across an ``EAGAIN`` send loop.
    """

    def __init__(self, sock: object, deadline_ms: int | None = None) -> None:
        self.io_socket = sock
        self._deadline_ms = deadline_ms

    def io_interest(self, now_ms: int) -> int:  # noqa: ARG002 (wait protocol)
        return _IO_WRITE

    def next_deadline(self, now_ms: int) -> int | None:  # noqa: ARG002 (wait protocol)
        return self._deadline_ms
