"""``ReadWait`` and ``WriteWait`` tell ``Runner.wait`` which socket a generator is waiting on.

A generator that ``Runner.add_generator`` drives yields one of them when a
socket would block.  ``Runner.wait`` then sleeps until the socket is ready or
``deadline_ms`` passes, and the next ``Runner.tick`` resumes the generator.
"""

from chumicro_sockets._connector import _IO_READ, _IO_WRITE


class ReadWait:
    """``ReadWait(sock)`` asks ``Runner.wait`` to wake when ``sock`` has bytes to read.

    Args:
        sock: The socket to watch.
        deadline_ms: Tick at which ``Runner.wait`` wakes even if ``sock`` stays
            idle, or ``None`` to wait on the socket alone.
    """

    def __init__(self, sock: object, deadline_ms: int | None = None) -> None:
        self.io_socket = sock
        self._deadline_ms = deadline_ms

    def io_interest(self, now_ms: int) -> int:  # noqa: ARG002 (wait protocol)
        return _IO_READ

    def next_deadline(self, now_ms: int) -> int | None:  # noqa: ARG002 (wait protocol)
        return self._deadline_ms


class WriteWait:
    """``WriteWait(sock)`` asks ``Runner.wait`` to wake when ``sock`` can take more bytes.

    Args:
        sock: The socket to watch.
        deadline_ms: Tick at which ``Runner.wait`` wakes even if ``sock`` stays
            full, or ``None`` to wait on the socket alone.
    """

    def __init__(self, sock: object, deadline_ms: int | None = None) -> None:
        self.io_socket = sock
        self._deadline_ms = deadline_ms

    def io_interest(self, now_ms: int) -> int:  # noqa: ARG002 (wait protocol)
        return _IO_WRITE

    def next_deadline(self, now_ms: int) -> int | None:  # noqa: ARG002 (wait protocol)
        return self._deadline_ms
