"""``FakeSocket`` — drives downstream tests without a real network.

Implements the full :class:`~chumicro_sockets.protocol.TCPClientSocket`
protocol against in-memory bytearrays.  Three knobs cover almost every
test pattern downstream libs need:

* :attr:`FakeSocket.sent` — bytes written via :meth:`send`.  Tests
  assert against this to confirm correct wire-format encoding.
* :meth:`enqueue_recv` — script bytes the next :meth:`recv_into`
  call(s) will return.  Multiple chunks queue in FIFO order.
* :meth:`enqueue_eagain` — script the next :meth:`send` or
  :meth:`recv_into` to raise ``OSError(11)``.  Lets tests exercise
  non-blocking partial-completion paths.

Idiom for downstream libs::

    from chumicro_sockets.testing import FakeSocket

    sock = FakeSocket()
    sock.enqueue_recv(b"\\x20\\x02\\x00\\x00")  # MQTT CONNACK
    client = MQTTClient(sock)
    client.connect()
    assert sock.sent.startswith(b"\\x10")        # CONNECT packet wire prefix

The fake's behaviour is deterministic: sends always succeed (modulo
scripted EAGAINs), recv_into reads from the queue head, and close
flips a flag so subsequent operations raise the same ``OSError`` a
real closed socket would.
"""


from collections import deque

# Errno 11 (EAGAIN) is the cross-runtime "would block" code.  Spelt
# out as a constant so callers don't have to remember the magic.
EAGAIN = 11


class FakeSocket:
    """In-memory ``TCPClientSocket`` for tests.

    All methods match the :class:`~chumicro_sockets.protocol.TCPClientSocket`
    protocol; in addition, :meth:`enqueue_recv` and
    :meth:`enqueue_eagain` script future behaviour and :attr:`sent`
    exposes the byte log.
    """

    def __init__(self) -> None:
        self.sent: bytearray = bytearray()
        self._recv_queue: deque[bytes] = deque()
        self._closed: bool = False
        self._blocking: bool = True
        self._timeout: float | None = None
        self._send_eagains: int = 0
        self._recv_eagains: int = 0
        # Optional explicit fd for tests that exercise select.poll
        # registration paths.  Defaults to a stable per-instance
        # int; `-1` advertises "no fd" the way CP-radio fakes do.
        self._fileno: int = id(self) & 0x7FFFFFFF

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

    def set_fileno(self, fd: int) -> None:
        """Override the integer fd :meth:`fileno` returns."""
        self._fileno = int(fd)

    # -- protocol surface ----------------------------------------------

    def send(self, data: bytes) -> int:
        """Write *data* into :attr:`sent` and return its length."""
        self._raise_if_closed()
        if self._send_eagains > 0:
            self._send_eagains -= 1
            raise OSError(EAGAIN, "would block")
        view = memoryview(data)
        self.sent.extend(view)
        return len(view)

    def recv_into(self, buffer: bytearray, nbytes: int = 0) -> int:
        """Pop the queue head, copy into *buffer*, return bytes written.

        Returns 0 when the queue is empty AND the socket isn't closed —
        that's the "peer sent nothing this tick" idiom.  When the
        socket is closed and the queue is exhausted, also returns 0
        (clean peer close).
        """
        self._raise_if_closed()
        if self._recv_eagains > 0:
            self._recv_eagains -= 1
            raise OSError(EAGAIN, "would block")
        if not self._recv_queue:
            return 0
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
        """Mark the socket closed.  Idempotent."""
        self._closed = True

    def setblocking(self, flag: bool) -> None:
        self._blocking = bool(flag)
        self._timeout = None if flag else 0.0

    def settimeout(self, seconds: float | None) -> None:
        self._timeout = seconds
        self._blocking = seconds is None

    def fileno(self) -> int:
        return self._fileno

    # -- introspection -------------------------------------------------

    @property
    def closed(self) -> bool:
        """``True`` when :meth:`close` has been called."""
        return self._closed

    @property
    def blocking(self) -> bool:
        """Reflects the most recent :meth:`setblocking` / :meth:`settimeout`."""
        return self._blocking

    @property
    def timeout(self) -> float | None:
        return self._timeout

    @property
    def pending_recv_chunks(self) -> int:
        """Number of unconsumed chunks left in the recv queue."""
        return len(self._recv_queue)

    # -- helpers -------------------------------------------------------

    def _raise_if_closed(self) -> None:
        if self._closed:
            # Stdlib raises OSError(EBADF=9) on a closed fd.  We pick
            # the same shape so downstream error-handling code that
            # checks ``except OSError`` works identically.
            raise OSError(9, "socket closed")
