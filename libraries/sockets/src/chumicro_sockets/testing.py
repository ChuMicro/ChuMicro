"""In-memory socket test doubles: ``FakeSocket``, ``FakeUDPSocket``, ``FakeSocketConnector``.

They implement the cross-runtime socket surface against in-memory buffers so
downstream tests exercise wire-format encoding, non-blocking partial-completion,
and the multi-tick connect path without a real network. ``enqueue_recv`` scripts
future reads, ``enqueue_eagain_for_send`` / ``enqueue_eagain_for_recv`` script
``OSError(EAGAIN)`` raises, and ``sent`` records what was written. Behavior is
deterministic: sends succeed except where an EAGAIN is scripted, reads come from
the queue head, and ``close`` makes later operations raise like a real socket.
"""

__chumicro_test_support__ = True


import errno
from collections import deque

# Cap on enqueued entries before the deque drops the oldest. No real test comes
# close, but MicroPython's ``deque`` requires a positive ``maxlen`` (no
# unbounded form), so this is a large stand-in for infinity.
_FAKE_SOCKET_QUEUE_MAXLEN = 1024

# Poll-interest bits for ``FakeSocketConnector.io_interest``; mirror
# ``chumicro_runner.IO_READ`` / ``IO_WRITE`` by value, held as literals so
# the sockets test support takes no runner dependency edge.
_IO_READ = 1
_IO_WRITE = 2


class FakeSocket:
    """In-memory TCP client socket for tests.

    Exposes the cross-runtime TCP surface (``send`` / ``recv_into`` /
    ``close`` / ``setblocking`` / ``settimeout``); in addition,
    :meth:`enqueue_recv` and :meth:`enqueue_eagain_for_send` /
    :meth:`enqueue_eagain_for_recv` script future behavior and
    :attr:`sent` exposes the byte log.
    """

    def __init__(self) -> None:
        self.sent: bytearray = bytearray()
        #: ``True`` after :meth:`close` has been called.
        self.closed: bool = False
        #: Reflects the most recent :meth:`setblocking` / :meth:`settimeout`.
        self.blocking: bool = True
        # ``deque((), maxlen)``: positional form required on MicroPython. Uses
        # the production libraries' primitive so MP deque quirks surface here.
        self._recv_queue: deque[bytes] = deque((), _FAKE_SOCKET_QUEUE_MAXLEN)
        # Peer-close (clean FIN), separate from own-side ``close()`` and set by
        # :meth:`simulate_peer_close`. When True, ``recv_into`` returns 0 once
        # the queue drains, matching a real non-blocking socket on a peer FIN.
        self._peer_closed: bool = False
        self._send_eagains: int = 0
        self._recv_eagains: int = 0

    # -- scripting ------------------------------------------------------

    def enqueue_recv(self, chunk: bytes) -> None:
        """Append *chunk* to the recv-side queue.

        Each :meth:`recv_into` pops one chunk off the head; a short read pushes
        the leftover back on the head, mimicking real socket fragmentation.
        """
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
        """Simulate a clean peer FIN: once the recv queue drains,
        :meth:`recv_into` returns 0 instead of raising EAGAIN.

        Separate from :meth:`close`, which models own-side close and makes every
        later operation raise ``OSError(EBADF)``.
        """
        self._peer_closed = True

    # -- protocol surface ----------------------------------------------

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
        """Pop the queue head into *buffer* and return the number of bytes written.

        Matches real non-blocking ``recv_into``: returns the copied count when
        the queue has data, returns 0 once the queue drains after
        :meth:`simulate_peer_close`, and otherwise raises ``OSError(EAGAIN)``
        (or ``OSError(EBADF)`` once closed).
        """
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

    # -- helpers -------------------------------------------------------

    def _raise_if_closed(self) -> None:
        if self.closed:
            # Stdlib raises OSError(EBADF) on a closed fd; match that shape so
            # downstream ``except OSError`` handling works identically.
            raise OSError(errno.EBADF, "socket closed")


class FakeUDPSocket:
    """In-memory UDP socket for tests.

    The datagram counterpart of :class:`FakeSocket`. Exposes the cross-runtime
    UDP surface (``sendto`` / ``recvfrom_into`` / ``close`` / ``setblocking`` /
    ``settimeout`` / ``getsockname``); :meth:`enqueue_recv` scripts future
    ``recvfrom_into`` returns and :attr:`sent` records every ``sendto`` as a
    ``(data, host, port)`` tuple.

    Args:
        bind_host: Reported by :meth:`getsockname` as the bound host. Defaults
            to ``"0.0.0.0"``.
        bind_port: Reported by :meth:`getsockname` as the bound port. Defaults
            to ``54321`` (a stand-in for an OS-assigned ephemeral port).
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
        # ``deque((), maxlen)``: see FakeSocket for the reasoning.
        self._recv_queue: deque = deque((), _FAKE_SOCKET_QUEUE_MAXLEN)
        self._send_eagains: int = 0
        self._recv_eagains: int = 0
        self._bind_host = bind_host
        self._bind_port = bind_port

    # -- scripting ------------------------------------------------------

    def enqueue_recv(
        self,
        data: bytes,
        *,
        host: str = "0.0.0.0",
        port: int = 0,
    ) -> None:
        """Append a datagram to the recv-side queue.

        The next :meth:`recvfrom_into` pops it off the head and copies up to
        ``len(buffer)`` bytes, truncating the rest as real UDP does. *host* and
        *port* identify the sender for tests that assert on who replied.
        """
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("enqueue_recv expects bytes-like")
        self._recv_queue.append((bytes(data), (host, port)))

    def enqueue_eagain_for_send(self, count: int = 1) -> None:
        """Script the next *count* :meth:`sendto` calls to raise EAGAIN."""
        self._send_eagains += int(count)

    def enqueue_eagain_for_recv(self, count: int = 1) -> None:
        """Script the next *count* :meth:`recvfrom_into` calls to raise EAGAIN."""
        self._recv_eagains += int(count)

    # -- protocol surface ----------------------------------------------

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
        """Pop a queued datagram into *buffer* and return ``(n, (host, port))``.

        Raises ``OSError(EAGAIN)`` when the queue is empty (a would-block, not a
        zero-length read); a genuine empty datagram still returns ``0``.
        Datagrams larger than the buffer are truncated, matching real UDP.
        """
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

    # -- helpers -------------------------------------------------------

    def _raise_if_closed(self) -> None:
        if self.closed:
            raise OSError(errno.EBADF, "socket closed")


class FakeSocketConnector:
    """Scriptable test double for :class:`SocketConnector`.

    Exposes the same observable surface as the real connector (``state``,
    ``socket``, ``last_error``, the ``io_*`` and ``check`` / ``handle`` /
    ``tick`` / ``next_deadline`` / ``cancel`` methods), but transitions come
    from a scripted list of action strings instead of real I/O. Each ``tick``
    (or ``handle``) consumes one action:

    * ``"dns_ok"``: ``awaiting_dns`` to ``awaiting_tcp``.
    * ``"tcp_pending"``: stay in ``awaiting_tcp``.
    * ``"tcp_ok"``: ``awaiting_tcp`` to ``awaiting_tls`` (if ``tls``) or ``ready``.
    * ``"tls_pending"``: stay in ``awaiting_tls`` and narrow ``io_interest`` to read.
    * ``"tls_ok"``: ``awaiting_tls`` to ``ready``.
    * ``"fail:<message>"``: transition to ``failed`` with *message* as ``last_error``.

    The ``socket`` attribute holds the :class:`FakeSocket` from ``awaiting_tcp``
    onward and clears to ``None`` on ``failed`` / ``cancel``, mirroring the real
    connector.
    """

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
        # Mirrors the real connector: read+write until the first handshake step
        # names a direction ("tls_pending" narrows to read).
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
            return  # No script left; stay put (test "wait one more tick" idioms).
        action = self._actions.pop(0)
        if action.startswith("fail:"):
            self.last_error = OSError(action[5:])
            self.state = "failed"
            self.socket = None
            return
        if action == "dns_ok" and self.state == "awaiting_dns":
            # The real connector builds its raw socket at TCP-connect
            # entry and keeps it on ``socket`` through ``ready``.
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
