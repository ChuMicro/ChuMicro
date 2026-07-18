"""The socket I/O wait vocabulary: ``ReadWait`` and ``WriteWait``."""

from chumicro_sockets._connector import _IO_READ, _IO_WRITE


class ReadWait:
    """Wait for *sock* to become readable, optionally bounded by a deadline."""

    def __init__(self, sock: object, deadline_ms: int | None = None) -> None:
        self.io_socket = sock
        self._deadline_ms = deadline_ms

    def io_interest(self, now_ms: int) -> int:  # noqa: ARG002 (wait protocol)
        return _IO_READ

    def next_deadline(self, now_ms: int) -> int | None:  # noqa: ARG002 (wait protocol)
        return self._deadline_ms


class WriteWait:
    """Wait for *sock* to become writable, optionally bounded by a deadline."""

    def __init__(self, sock: object, deadline_ms: int | None = None) -> None:
        self.io_socket = sock
        self._deadline_ms = deadline_ms

    def io_interest(self, now_ms: int) -> int:  # noqa: ARG002 (wait protocol)
        return _IO_WRITE

    def next_deadline(self, now_ms: int) -> int | None:  # noqa: ARG002 (wait protocol)
        return self._deadline_ms
