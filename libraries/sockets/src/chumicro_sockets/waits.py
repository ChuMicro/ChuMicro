"""The socket I/O wait vocabulary: ``ReadWait`` and ``WriteWait``.

A generator doing non-blocking socket I/O yields one of these on ``EAGAIN`` so
a tick-based scheduler learns which poll direction to wait on before it resumes
the generator. Each marker carries one socket (read via ``io_socket``), reports
one poll direction (``io_interest``), and takes an optional absolute deadline
(``next_deadline``). They live here rather than in a scheduler package because
they carry a socket, and this library never imports the loop that drives it.
Build one before an ``EAGAIN`` loop and re-yield the same instance every spin so
a steady loop allocates nothing.
"""

from chumicro_sockets._connector import _IO_READ, _IO_WRITE


class ReadWait:
    """Wait for *sock* to become readable, optionally bounded by a deadline.

    Reports ``IO_READ`` interest and carries *sock* for the scheduler to
    register. ``deadline_ms`` is an absolute ``ticks_ms`` tick to wake at even
    if no bytes arrive, or ``None`` to wait on the poll indefinitely.
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
    register. ``deadline_ms`` is an absolute ``ticks_ms`` tick to wake at even
    if the socket never drains, or ``None`` to wait on the poll indefinitely.
    """

    def __init__(self, sock: object, deadline_ms: int | None = None) -> None:
        self.io_socket = sock
        self._deadline_ms = deadline_ms

    def io_interest(self, now_ms: int) -> int:  # noqa: ARG002 (wait protocol)
        return _IO_WRITE

    def next_deadline(self, now_ms: int) -> int | None:  # noqa: ARG002 (wait protocol)
        return self._deadline_ms
