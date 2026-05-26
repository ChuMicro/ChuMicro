"""Generator helpers for runner-driven sequential I/O.

Sub-module — opt-in via explicit import::

    from chumicro_runner.generators import connect, recv_until, send_all

The four helpers — ``connect``, ``send_all``, ``recv_until``,
``recv_exact`` — let a generator-driven service express its full
lifecycle top-to-bottom::

    def echo_run(connector):
        sock = yield from connect(connector)
        try:
            yield from send_all(sock, b"hello\\n")
            reply = yield from recv_until(sock, b"\\n", max_bytes=4096)
        finally:
            sock.close()

The helpers operate on **duck-typed** inputs:

* ``connect`` takes any object exposing the
  ``state`` / ``socket`` / ``last_error`` / ``io_socket`` /
  ``io_wants_read`` / ``io_wants_write`` / ``tick`` / ``cancel``
  contract — the same contract ``chumicro_sockets.SocketConnector``
  satisfies (and that test stand-ins like
  ``chumicro_sockets.testing.FakeSocketConnector`` reproduce).  The
  helper yields the connector directly so the wrapper's poll-set
  registration follows the connector's own ``io_*`` attributes
  through DNS / TCP / TLS / ready.
* ``send_all`` / ``recv_until`` / ``recv_exact`` take any object
  exposing ``send`` / ``recv_into`` that returns / raises
  ``OSError(EAGAIN)`` like a non-blocking socket — what
  ``chumicro_sockets.tcp_client_socket`` / ``FakeSocket`` provide.
  These helpers yield small private wait objects (see the
  ``_ReadWait`` / ``_WriteWait`` classes below) that carry the
  socket reference for poll-set registration.

The wrapper in ``_generator`` does not isinstance-check anything.
Any object exposing ``io_socket`` / ``io_wants_read`` /
``io_wants_write`` / ``next_deadline`` works as a wait.  Custom
services can implement that shape directly.

Heap-DoS protection: ``recv_until`` requires ``max_bytes`` and
refuses peer input above it; ``recv_exact`` allocates a fixed buffer
of the requested size.  Both reject non-positive sizes up front.
"""

import errno


class _ReadWait:
    """Private read-wait shape — ``io_socket`` + ``io_wants_read=True``."""

    io_wants_read = True

    def __init__(self, sock: object) -> None:
        self.io_socket = sock


class _WriteWait:
    """Private write-wait shape — ``io_socket`` + ``io_wants_write=True``."""

    io_wants_write = True

    def __init__(self, sock: object) -> None:
        self.io_socket = sock


class _DeadlineWait:
    """Private deadline-wait shape — ``next_deadline=until_ms``."""

    def __init__(self, until_ms: int) -> None:
        self.next_deadline = until_ms


def sleep_until(until_ms: int) -> object:
    """Suspend the generator until ``ticks_ms() >= until_ms``.

    The wrapper reads ``next_deadline`` off the yielded wait and
    contributes it to ``Runner.wait``'s ipoll timeout so the loop
    sleeps efficiently between sleep-only services.

    Compute *until_ms* via ``ticks_add(ticks_ms(), delay_ms)`` —
    treating it as an absolute tick (wrap-safe) rather than a delay
    means a single yield won't drift across long pauses.

    Args:
        until_ms: Absolute ``ticks_ms`` value at which to resume.

    Yields:
        A private deadline-wait carrying *until_ms*.
    """
    yield _DeadlineWait(until_ms)


def connect(connector: object) -> object:
    """Drive *connector* across runner ticks; return its connected socket.

    Yields the connector itself on every tick so the wrapper reads
    ``connector.io_socket`` / ``io_wants_read`` / ``io_wants_write``
    directly — the connector's own attribute progression through
    DNS -> TCP -> (TLS) -> ready is what gates the ipoll
    registration.  Returns the connected, non-blocking socket via
    PEP 380 — call as ``sock = yield from connect(connector)``.

    The connector's per-phase blocking compromises still apply:
    CircuitPython's TCP+TLS collapse into one blocking ``connect()``
    inside a single tick; MicroPython's TLS handshake blocks inline.
    The synchronous-tick parts of those phases stall the runner for
    their duration — no different from driving the connector under a
    check / handle service.

    On cancellation (``GeneratorExit``) or failure, the connector's
    ``cancel`` runs in a ``finally`` block so any in-flight socket
    closes cleanly.

    Args:
        connector: Any object exposing the
            ``chumicro_sockets.SocketConnector`` surface — ``state``,
            ``socket``, ``last_error``, ``io_socket``, ``io_wants_read``,
            ``io_wants_write``, ``tick(now_ms)``, ``cancel()``.  The
            real ``tcp_client_connector`` / ``tls_client_connector``
            return such objects; ``FakeSocketConnector`` in
            ``chumicro_sockets.testing`` is the test stand-in.

    Yields:
        The connector itself, repeatedly, until terminal.

    Returns:
        Connected socket — non-blocking, ready for ``send`` /
        ``recv_into``.  The caller owns lifecycle (``sock.close()``
        in a ``try / finally`` or ``with`` block).

    Raises:
        OSError: Connector reached ``failed`` (DNS lookup, TCP
            connect, or TLS handshake failed).  The connector's
            ``last_error`` is what's raised.
    """
    sock = None
    try:
        while True:
            connector.tick(0)
            state = connector.state
            if state == "ready":
                sock = connector.socket
                return sock
            if state == "failed":
                raise connector.last_error
            yield connector
    finally:
        if sock is None:
            connector.cancel()


def send_all(sock: object, data: object) -> object:
    """Send every byte of *data*, yielding on ``EAGAIN``.

    Loops on ``sock.send`` until the whole buffer is written.  Each
    EAGAIN yields a single cached ``_WriteWait(sock)`` — the helper
    allocates the wait once outside the loop so steady-state
    iterations are zero-allocation.

    Args:
        sock: Non-blocking TCP socket (typically returned by
            :func:`connect`).
        data: Bytes-like object to transmit.

    Yields:
        A private write-wait carrying *sock* on each EAGAIN.

    Raises:
        OSError: Peer closed mid-send (``send`` returned 0) or the
            socket reported a non-EAGAIN error.
    """
    view = memoryview(data)
    total = len(view)
    offset = 0
    write_wait = _WriteWait(sock)
    while offset < total:
        try:
            sent = sock.send(view[offset:])
        except OSError as error:
            if error.args[0] == errno.EAGAIN:
                yield write_wait
                continue
            raise
        if sent == 0:
            raise OSError("peer closed during send")
        offset += sent


def recv_until(sock: object, separator: object, *, max_bytes: int) -> bytes:
    """Read bytes until *separator* appears; return everything up to and including it.

    Loops on ``sock.recv_into`` into a 256-byte scratch buffer,
    extending an accumulator until ``separator in accumulator`` or
    growth would exceed *max_bytes*.  Each EAGAIN yields a single
    cached private read-wait carrying *sock*.

    Args:
        sock: Non-blocking TCP socket.
        separator: Bytes pattern that terminates the read (e.g.
            ``b"\\r\\n"`` for HTTP, ``b"\\n"`` for line-oriented).
        max_bytes: Hard cap on accumulated bytes.  The helper refuses
            input above this — required because the peer controls
            how much they send before the separator arrives, and an
            unbounded sink is heap-DoS surface on a 256 KB device.

    Yields:
        A private read-wait on each EAGAIN.

    Returns:
        ``bytes`` — from the start through the first occurrence of
        *separator*, inclusive.  Bytes received past the separator
        in the same ``recv_into`` chunk are discarded; this helper is
        for one-shot reads where the peer does not pipeline.  For
        framed protocols where pipelining is normal, drive the
        socket through a stateful buffer instead.

    Raises:
        OSError: Peer closed before the separator arrived, growth
            exceeded *max_bytes*, or the socket reported a non-EAGAIN
            error.
        ValueError: *max_bytes* is not positive.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    accumulator = bytearray()
    chunk = bytearray(256)
    chunk_view = memoryview(chunk)
    read_wait = _ReadWait(sock)
    sep_length = len(separator)

    while True:
        try:
            nbytes = sock.recv_into(chunk)
        except OSError as error:
            if error.args[0] == errno.EAGAIN:
                yield read_wait
                continue
            raise
        if nbytes == 0:
            raise OSError("peer closed before separator")
        if len(accumulator) + nbytes > max_bytes:
            raise OSError("recv_until exceeded max_bytes")
        accumulator.extend(chunk_view[:nbytes])
        sep_index = accumulator.find(separator)
        if sep_index != -1:
            return bytes(accumulator[: sep_index + sep_length])


def recv_exact(sock: object, byte_count: int) -> bytes:
    """Read exactly *byte_count* bytes; return them as ``bytes``.

    Loops on ``sock.recv_into`` into a pre-allocated *byte_count*-byte
    buffer, advancing an offset across yields.  Each EAGAIN yields a
    single cached private read-wait carrying *sock*.

    Args:
        sock: Non-blocking TCP socket.
        byte_count: Number of bytes to read.  Must be positive.

    Yields:
        A private read-wait on each EAGAIN.

    Returns:
        ``bytes`` of length exactly *byte_count*.

    Raises:
        OSError: Peer closed before *byte_count* bytes arrived, or the
            socket reported a non-EAGAIN error.
        ValueError: *byte_count* is not positive.
    """
    if byte_count <= 0:
        raise ValueError("byte_count must be positive")

    buffer = bytearray(byte_count)
    view = memoryview(buffer)
    offset = 0
    read_wait = _ReadWait(sock)

    while offset < byte_count:
        try:
            nbytes = sock.recv_into(view[offset:])
        except OSError as error:
            if error.args[0] == errno.EAGAIN:
                yield read_wait
                continue
            raise
        if nbytes == 0:
            raise OSError("peer closed before byte_count bytes")
        offset += nbytes

    return bytes(buffer)
