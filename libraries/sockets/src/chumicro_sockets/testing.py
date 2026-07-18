"""In-memory socket test doubles: ``FakeSocket``, ``FakeUDPSocket``, ``FakeSocketConnector``."""

__chumicro_test_support__ = True


import errno
from collections import deque

# MicroPython's ``deque`` requires a positive ``maxlen`` (no unbounded form);
# 1024 is a large stand-in for infinity.
_FAKE_SOCKET_QUEUE_MAXLEN = 1024

# Mirror ``chumicro_runner.IO_READ`` / ``IO_WRITE`` by value; kept as literals so
# the test support takes no runner dependency edge.
_IO_READ = 1
_IO_WRITE = 2


class FakeSocket:
    """In-memory TCP client socket for tests."""

    def __init__(self) -> None:
        self.sent: bytearray = bytearray()
        self.closed: bool = False
        self.blocking: bool = True
        # Positional ``deque((), maxlen)`` form: MicroPython requires it.
        self._recv_queue: deque[bytes] = deque((), _FAKE_SOCKET_QUEUE_MAXLEN)
        self._peer_closed: bool = False
        self._send_eagains: int = 0
        self._recv_eagains: int = 0

    def enqueue_recv(self, chunk: bytes) -> None:
        """Append *chunk* to the recv-side queue."""
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise TypeError("enqueue_recv expects bytes-like")
        self._recv_queue.append(bytes(chunk))

    def enqueue_eagain_for_send(self, count: int = 1) -> None:
        """Script the next *count* :meth:`send` calls to raise EAGAIN."""
        self._send_eagains += int(count)

    def enqueue_eagain_for_recv(self, count: int = 1) -> None:
        """Script the next *count* :meth:`recv_into` calls to raise EAGAIN."""
        self._recv_eagains += int(count)

    def simulate_peer_close(self) -> None:
        """Simulate a clean peer FIN so ``recv_into`` returns 0 once the queue drains."""
        self._peer_closed = True

    def send(self, data: bytes) -> int:
        """Write *data* into :attr:`sent` and return its length."""
        self._raise_if_closed()
        if self._send_eagains > 0:
            self._send_eagains -= 1
            raise OSError(errno.EAGAIN, "would block")
        view = memoryview(data)
        self.sent.extend(view)
        return len(view)

    def recv_into(self, buffer: bytearray, nbytes: int = 0) -> int:
        """Pop the queue head into *buffer* and return the number of bytes written."""
        self._raise_if_closed()
        if self._recv_eagains > 0:
            self._recv_eagains -= 1
            raise OSError(errno.EAGAIN, "would block")
        if not self._recv_queue:
            if self._peer_closed:
                return 0
            raise OSError(errno.EAGAIN, "would block")
        capacity = nbytes if nbytes > 0 else len(buffer)
        if capacity <= 0:
            return 0
        chunk = self._recv_queue.popleft()
        consumed = min(capacity, len(chunk))
        buffer[:consumed] = chunk[:consumed]
        if consumed < len(chunk):
            self._recv_queue.appendleft(chunk[consumed:])
        return consumed

    def close(self) -> None:
        """Mark the socket closed."""
        self.closed = True

    def setblocking(self, flag: bool) -> None:
        self.blocking = bool(flag)

    def settimeout(self, seconds: float | None) -> None:
        self.blocking = seconds is None

    def _raise_if_closed(self) -> None:
        if self.closed:
            # Match stdlib's OSError(EBADF) on a closed fd.
            raise OSError(errno.EBADF, "socket closed")


class FakeUDPSocket:
    """In-memory UDP socket for tests.

    Args:
        bind_host: Reported by :meth:`getsockname` as the bound host.
        bind_port: Reported by :meth:`getsockname` as the bound port.
    """

    def __init__(
        self,
        bind_host: str = "0.0.0.0",
        bind_port: int = 54321,
    ) -> None:
        self.sent: list = []
        #: ``True`` after :meth:`close` has been called.
        self.closed: bool = False
        #: Reflects the most recent :meth:`setblocking` / :meth:`settimeout`.
        self.blocking: bool = True
        # Positional ``deque((), maxlen)`` form: MicroPython requires it.
        self._recv_queue: deque = deque((), _FAKE_SOCKET_QUEUE_MAXLEN)
        self._send_eagains: int = 0
        self._recv_eagains: int = 0
        self._bind_host = bind_host
        self._bind_port = bind_port

    def enqueue_recv(
        self,
        data: bytes,
        *,
        host: str = "0.0.0.0",
        port: int = 0,
    ) -> None:
        """Append a datagram to the recv-side queue."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("enqueue_recv expects bytes-like")
        self._recv_queue.append((bytes(data), (host, port)))

    def enqueue_eagain_for_send(self, count: int = 1) -> None:
        """Script the next *count* :meth:`sendto` calls to raise EAGAIN."""
        self._send_eagains += int(count)

    def enqueue_eagain_for_recv(self, count: int = 1) -> None:
        """Script the next *count* :meth:`recvfrom_into` calls to raise EAGAIN."""
        self._recv_eagains += int(count)

    def sendto(self, data: bytes, host: str, port: int) -> int:
        """Append ``(bytes(data), host, port)`` to :attr:`sent`."""
        self._raise_if_closed()
        if self._send_eagains > 0:
            self._send_eagains -= 1
            raise OSError(errno.EAGAIN, "would block")
        view = memoryview(data)
        self.sent.append((bytes(view), host, port))
        return len(view)

    def recvfrom_into(self, buffer: bytearray, nbytes: int = 0) -> tuple:
        """Pop a queued datagram into *buffer* and return ``(n, (host, port))``."""
        self._raise_if_closed()
        if self._recv_eagains > 0:
            self._recv_eagains -= 1
            raise OSError(errno.EAGAIN, "would block")
        if not self._recv_queue:
            raise OSError(errno.EAGAIN, "would block")
        capacity = nbytes if nbytes > 0 else len(buffer)
        data, address = self._recv_queue.popleft()
        consumed = min(capacity, len(data))
        if consumed:
            buffer[:consumed] = data[:consumed]
        return consumed, address

    def close(self) -> None:
        """Mark the socket closed."""
        self.closed = True

    def setblocking(self, flag: bool) -> None:
        self.blocking = bool(flag)

    def settimeout(self, seconds: float | None) -> None:
        self.blocking = seconds is None

    def getsockname(self) -> tuple:
        """Report the bound ``(host, port)`` tuple given at construction."""
        return self._bind_host, self._bind_port

    def _raise_if_closed(self) -> None:
        if self.closed:
            raise OSError(errno.EBADF, "socket closed")


class FakeSocketConnector:
    """Scriptable test double for :class:`SocketConnector`."""

    def __init__(
        self,
        host: str = "test.example",
        port: int = 1883,
        *,
        tls: bool = False,
        actions: list[str] | None = None,
        socket: FakeSocket | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._tls = tls
        self._actions = list(actions) if actions is not None else []
        self._target_socket = socket if socket is not None else FakeSocket()

        self.state = "awaiting_dns"
        self.socket: FakeSocket | None = None
        self.last_error: Exception | None = None
        # read+write until the first handshake step narrows to one direction.
        self._tls_interest = _IO_READ | _IO_WRITE

    @property
    def io_socket(self) -> object | None:
        """The socket for ``Runner.wait`` once built, or ``None`` before and after."""
        if self.socket is None:
            return None
        return self.socket

    def io_interest(self, now_ms: int) -> int:  # noqa: ARG002 (runner contract)
        """Poll-interest bitmask matching the real ``SocketConnector``: the
        handshake direction during ``awaiting_tls``, write during
        ``awaiting_tcp``, nothing else."""
        if self.state == "awaiting_tls":
            return self._tls_interest
        if self.state == "awaiting_tcp":
            return _IO_WRITE
        return 0

    def check(self, now_ms: int) -> bool:  # noqa: ARG002 (runner contract)
        return self.state not in ("ready", "failed")

    def handle(self, now_ms: int) -> None:
        self.tick(now_ms)

    def next_deadline(self, now_ms: int) -> int | None:  # noqa: ARG002
        return None

    def tick(self, now_ms: int) -> None:  # noqa: ARG002
        if self.state in ("ready", "failed"):
            return
        if not self._actions:
            return
        action = self._actions.pop(0)
        if action.startswith("fail:"):
            self.last_error = OSError(action[5:])
            self.state = "failed"
            self.socket = None
            return
        if action == "dns_ok" and self.state == "awaiting_dns":
            self.socket = self._target_socket
            self.state = "awaiting_tcp"
            return
        if action == "tcp_pending" and self.state == "awaiting_tcp":
            return
        if action == "tcp_ok" and self.state == "awaiting_tcp":
            if self._tls:
                self.state = "awaiting_tls"
            else:
                self.state = "ready"
            return
        if action == "tls_pending" and self.state == "awaiting_tls":
            self._tls_interest = _IO_READ
            return
        if action == "tls_ok" and self.state == "awaiting_tls":
            self.state = "ready"
            return
        raise AssertionError(
            f"FakeSocketConnector: action {action!r} not valid in "
            f"state {self.state!r}",
        )

    def cancel(self) -> None:
        if self.state in ("ready", "failed"):
            return
        if self.last_error is None:
            self.last_error = OSError("connector cancelled")
        self.socket = None
        self.state = "failed"
