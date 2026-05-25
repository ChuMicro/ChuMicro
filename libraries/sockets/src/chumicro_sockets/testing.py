"""``FakeSocket`` — drives downstream tests without a real network.

Implements the full TCP client socket surface
(``send`` / ``recv_into`` / ``close`` / ``setblocking`` / ``settimeout``)
against in-memory bytearrays.  Three knobs cover almost every test
pattern downstream libs need:

* :attr:`FakeSocket.sent` — bytes written via :meth:`send`.  Tests
  assert against this to confirm correct wire-format encoding.
* :meth:`enqueue_recv` — script bytes the next :meth:`recv_into`
  call(s) will return.  Multiple chunks queue in FIFO order.
* :meth:`enqueue_eagain` — script the next :meth:`send` or
  :meth:`recv_into` to raise ``OSError(errno.EAGAIN)``.  Lets tests
  exercise non-blocking partial-completion paths.

Idiom for downstream libs::

    from chumicro_sockets.testing import FakeSocket

    sock = FakeSocket()
    sock.enqueue_recv(b"\\x20\\x02\\x00\\x00")  # MQTT CONNACK
    client = MQTTClient(sock)
    client.connect()
    assert sock.sent.startswith(b"\\x10")        # CONNECT packet wire prefix

The fake's behavior is deterministic: sends always succeed (modulo
scripted EAGAINs), recv_into reads from the queue head, and close
flips a flag so subsequent operations raise the same ``OSError`` a
real closed socket would.
"""

__chumicro_test_support__ = True


import errno
from collections import deque

# Upper bound on enqueued bytes / datagrams a test can script before
# the deque starts dropping the oldest entry.  No real test comes
# close — but MicroPython's ``deque`` requires a positive ``maxlen``
# (no unbounded form), so we pick a value that's effectively infinite
# for test purposes while staying with the deque primitive that
# library code uses (``patterns.md`` §"FIFO queues use ``deque``").
_FAKE_SOCKET_QUEUE_MAXLEN = 1024


class FakeSocket:
    """In-memory TCP client socket for tests.

    Exposes the cross-runtime TCP surface (``send`` / ``recv_into`` /
    ``close`` / ``setblocking`` / ``settimeout``); in addition,
    :meth:`enqueue_recv` and :meth:`enqueue_eagain` script future
    behavior and :attr:`sent` exposes the byte log.
    """

    def __init__(self) -> None:
        self.sent: bytearray = bytearray()
        # ``deque((), maxlen)`` — positional form is required on
        # MicroPython.  We deliberately exercise the same primitive
        # the production libraries use (mqtt, websockets, events…)
        # so any future MP-specific deque quirks surface here too.
        self._recv_queue: deque[bytes] = deque((), _FAKE_SOCKET_QUEUE_MAXLEN)
        self._closed: bool = False
        # Peer-close (clean FIN) is separate from own-side ``close()``.
        # Set by :meth:`simulate_peer_close`.  When True, ``recv_into``
        # returns 0 once the queue drains — matching real non-blocking
        # ``recv_into`` semantics on CPython / MicroPython / CircuitPython
        # where a connected non-blocking socket returns 0 only on a
        # peer FIN, never on a quiet line (which raises EAGAIN).
        self._peer_closed: bool = False
        self._blocking: bool = True
        self._send_eagains: int = 0
        self._recv_eagains: int = 0

    # -- scripting ------------------------------------------------------

    def enqueue_recv(self, chunk: bytes) -> None:
        """Append *chunk* to the recv-side queue.

        Each :meth:`recv_into` call pops one chunk off the head and
        copies up to ``nbytes`` bytes from it.  If ``nbytes`` is
        smaller than the chunk, the leftover bytes are pushed back
        on the head — mimics how a real socket fragments reads.
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
        """Simulate a clean peer FIN — once the recv queue drains,
        :meth:`recv_into` returns 0 instead of raising EAGAIN.

        Separate from :meth:`close` (which models own-side close and
        makes every subsequent operation raise ``OSError(EBADF)``).
        Use this to exercise the broker-graceful-disconnect / peer-FIN
        path without losing the ability to script remaining bytes
        (e.g. a final DISCONNECT packet) before the FIN.
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
        """Pop the queue head, copy into *buffer*, return bytes written.

        Matches real non-blocking ``recv_into`` semantics on CPython,
        MicroPython lwIP, and CircuitPython lwIP:

        * Queue non-empty: return ``min(capacity, chunk_length)`` bytes.
        * Queue empty AND :meth:`simulate_peer_close` was called: return
          0 (clean peer FIN).
        * Queue empty otherwise: raise ``OSError(EAGAIN)`` (no data this
          tick on a still-connected socket).
        * Socket :meth:`close`'d: raise ``OSError(EBADF)``.
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
        self._closed = True

    def setblocking(self, flag: bool) -> None:
        self._blocking = bool(flag)

    def settimeout(self, seconds: float | None) -> None:
        self._blocking = seconds is None

    # -- introspection -------------------------------------------------

    @property
    def closed(self) -> bool:
        """``True`` when :meth:`close` has been called."""
        return self._closed

    @property
    def blocking(self) -> bool:
        """Reflects the most recent :meth:`setblocking` / :meth:`settimeout`."""
        return self._blocking

    # -- helpers -------------------------------------------------------

    def _raise_if_closed(self) -> None:
        if self._closed:
            # Stdlib raises OSError(EBADF=9) on a closed fd.  We pick
            # the same shape so downstream error-handling code that
            # checks ``except OSError`` works identically.
            raise OSError(errno.EBADF, "socket closed")


class FakeUDPSocket:
    """In-memory UDP socket for tests.

    Datagram-shaped counterpart of :class:`FakeSocket`.  Exposes the
    cross-runtime UDP surface (``sendto`` / ``recvfrom_into`` /
    ``close`` / ``setblocking`` / ``settimeout`` / ``getsockname``);
    plus :meth:`enqueue_recv` scripts future ``recvfrom_into`` returns
    and :attr:`sent` exposes the byte log of every ``sendto`` call as
    ``(data, host, port)`` tuples.

    Idiom for downstream tests::

        from chumicro_sockets.testing import FakeUDPSocket

        sock = FakeUDPSocket()
        sock.enqueue_recv(b"reply", host="10.0.0.5", port=123)
        client = NTPClient(sock=sock)
        client.send_request("10.0.0.5")

        assert sock.sent[0] == (b"<48-byte NTP request>", "10.0.0.5", 123)

    Args:
        bind_host: Reported by :meth:`getsockname` as the locally-bound
            host.  Defaults to ``"0.0.0.0"``.
        bind_port: Reported by :meth:`getsockname` as the locally-bound
            port.  Defaults to ``54321`` (a stand-in for an OS-assigned
            ephemeral port).
    """

    def __init__(
        self,
        bind_host: str = "0.0.0.0",
        bind_port: int = 54321,
    ) -> None:
        self.sent: list = []
        # ``deque((), maxlen)`` — see FakeSocket for the reasoning.
        self._recv_queue: deque = deque((), _FAKE_SOCKET_QUEUE_MAXLEN)
        self._closed: bool = False
        self._blocking: bool = True
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

        The next :meth:`recvfrom_into` call pops it off the head and
        copies up to ``len(buffer)`` bytes from it (truncates the rest
        — matches real UDP semantics).  *host* and *port* identify the
        sender; tests assert against them when their protocol cares
        who replied.
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
        """Pop a queued datagram into *buffer*, return ``(n, (host, port))``.

        Returns ``(0, ("0.0.0.0", 0))`` when the queue is empty — UDP
        has no peer-close, so an empty queue and a non-blocking socket
        is just "no datagram this tick".  Datagrams larger than
        ``nbytes`` (or ``len(buffer)`` when ``nbytes=0``) are
        truncated; the unread tail is discarded — matches real UDP.
        """
        self._raise_if_closed()
        if self._recv_eagains > 0:
            self._recv_eagains -= 1
            raise OSError(errno.EAGAIN, "would block")
        if not self._recv_queue:
            return 0, ("0.0.0.0", 0)
        capacity = nbytes if nbytes > 0 else len(buffer)
        data, address = self._recv_queue.popleft()
        consumed = min(capacity, len(data))
        if consumed:
            buffer[:consumed] = data[:consumed]
        return consumed, address

    def close(self) -> None:
        """Mark the socket closed."""
        self._closed = True

    def setblocking(self, flag: bool) -> None:
        self._blocking = bool(flag)

    def settimeout(self, seconds: float | None) -> None:
        self._blocking = seconds is None

    def getsockname(self) -> tuple:
        """Report the bound ``(host, port)`` tuple given at construction."""
        return self._bind_host, self._bind_port

    # -- introspection -------------------------------------------------

    @property
    def closed(self) -> bool:
        """``True`` when :meth:`close` has been called."""
        return self._closed

    @property
    def blocking(self) -> bool:
        return self._blocking

    # -- helpers -------------------------------------------------------

    def _raise_if_closed(self) -> None:
        if self._closed:
            raise OSError(errno.EBADF, "socket closed")


class FakeSocketConnector:
    """Scriptable test double for :class:`SocketConnector`.

    Same observable surface as the real connector — ``state``,
    ``socket``, ``last_error``, ``io_*``, ``check`` / ``handle`` /
    ``tick`` / ``next_deadline`` / ``cancel`` — but transitions are
    driven by an in-test script instead of real network I/O.

    Construct with a list of step actions; each call to ``tick`` (or
    ``handle``) consumes one action.  Actions are short strings:

    * ``"dns_ok"`` — ``awaiting_dns`` → ``awaiting_tcp``.
    * ``"tcp_pending"`` — stay in ``awaiting_tcp`` (simulates an
      EINPROGRESS round-trip).
    * ``"tcp_ok"`` — ``awaiting_tcp`` → ``awaiting_tls`` (if ``tls``)
      or ``ready``.
    * ``"tls_pending"`` — stay in ``awaiting_tls`` (simulates a
      handshake round that wants more data).
    * ``"tls_ok"`` — ``awaiting_tls`` → ``ready``.
    * ``"fail:<message>"`` — transition to ``failed`` with the given
      message as ``last_error``.

    The fake's ``socket`` attribute is set to the :class:`FakeSocket`
    passed in at construction (or a fresh one if none given) when the
    connector reaches ``ready``.

    Use this in consumer-side unit tests (``MQTTClient`` against the
    multi-tick connect path).  Real-network tests live in the adapter
    test files.
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

    @property
    def io_socket(self) -> object | None:
        if self.state in ("ready", "failed"):
            return None
        return self._target_socket

    @property
    def io_wants_read(self) -> bool:
        return self.state == "awaiting_tls"

    @property
    def io_wants_write(self) -> bool:
        return self.state in ("awaiting_tcp", "awaiting_tls")

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
            return  # No script left; stay where we are (useful for
            # exercising "wait one more tick" idioms in consumers).
        action = self._actions.pop(0)
        if action.startswith("fail:"):
            self.last_error = OSError(action[5:])
            self.state = "failed"
            return
        if action == "dns_ok" and self.state == "awaiting_dns":
            self.state = "awaiting_tcp"
            return
        if action == "tcp_pending" and self.state == "awaiting_tcp":
            return
        if action == "tcp_ok" and self.state == "awaiting_tcp":
            if self._tls:
                self.state = "awaiting_tls"
            else:
                self.socket = self._target_socket
                self.state = "ready"
            return
        if action == "tls_pending" and self.state == "awaiting_tls":
            return
        if action == "tls_ok" and self.state == "awaiting_tls":
            self.socket = self._target_socket
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
        self.state = "failed"
