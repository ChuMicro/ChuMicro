"""``chumicro_sockets.generators`` runs socket I/O as ``yield from`` steps inside a generator
that ``Runner.add_generator`` drives.

``connect`` drives a connector until it hands back a connected socket,
``send_all`` writes a whole buffer, and ``recv_until`` reads up to a
separator.  Each helper yields whenever the socket would block.
``Runner.wait`` then sleeps until the socket is ready, and the next
``Runner.tick`` resumes the generator.
"""

import errno

from chumicro_sockets._connector import STATE_FAILED, STATE_READY
from chumicro_sockets.waits import ReadWait, WriteWait


def connect(
    connector: object,
    *,
    timeout_ms: int | None = None,
    ticks: object | None = None,
) -> object:
    """Drive ``connector`` until it connects, and return the connected socket.

    Call it as ``sock = yield from connect(connector)``.  On success the
    caller owns the socket and closes it.  On failure, on timeout, or when the
    generator is closed, ``connect`` cancels the connector, which closes any
    half-open socket.  The connector's blocking steps still hold the main
    loop: the DNS lookup on every runtime, the TCP connect on CircuitPython,
    and the TLS handshake on CircuitPython and MicroPython.

    Args:
        connector: Connector from ``chumicro_sockets.connector``.
        timeout_ms: Time limit for the whole connect, in ms, or ``None`` to
            wait as long as the connector takes.  The limit is checked between
            steps, so it cannot cut a blocking step short.
        ticks: Clock with ``ticks_ms``, ``ticks_diff``, and ``ticks_add``,
            such as ``chumicro_timing.ticks``.  Required with ``timeout_ms``.

    Yields:
        The connector, for the runner to poll, until it reaches ``"ready"``
            or ``"failed"``.

    Returns:
        The connected socket.  CircuitPython hands it back in blocking mode.

    Raises:
        OSError: ``timeout_ms`` passed, with ``errno.ETIMEDOUT``.
        Exception: The connector failed.  ``connect`` raises its
            ``last_error``, such as an ``OSError`` for a refused connection.
        ValueError: ``timeout_ms`` was given without ``ticks``.
    """
    if timeout_ms is not None and ticks is None:
        raise ValueError("connect(timeout_ms=...) requires a ticks source")
    sock = None
    now_ms = 0
    deadline_ms = (
        ticks.ticks_add(ticks.ticks_ms(), timeout_ms)
        if timeout_ms is not None
        else None
    )
    try:
        while True:
            connector.tick(now_ms)
            state = connector.state
            if state == STATE_READY:
                sock = connector.socket
                return sock
            if state == STATE_FAILED:
                raise connector.last_error
            if (
                deadline_ms is not None
                and ticks.ticks_diff(deadline_ms, ticks.ticks_ms()) <= 0
            ):
                raise OSError(errno.ETIMEDOUT, "connect timed out")
            now_ms = yield connector
    finally:
        if sock is None:
            connector.cancel()


def send_all(sock: object, data: object) -> object:
    """Send every byte of ``data`` on ``sock``, yielding while the socket's send buffer is full.

    Call it as ``yield from send_all(sock, data)``.  Each time ``send``
    raises ``EAGAIN``, the helper yields a ``WriteWait``, which tells
    ``Runner.wait`` to wake when the socket can take more bytes.

    Args:
        sock: Connected non-blocking TCP socket.
        data: ``bytes``, ``bytearray``, or ``memoryview`` to send.

    Yields:
        A ``WriteWait`` on ``sock`` each time the socket would block.

    Raises:
        OSError: ``send`` returned 0 because the peer closed, or failed with
            an error other than ``EAGAIN``.
    """
    view = memoryview(data)
    total = len(view)
    offset = 0
    write_wait = WriteWait(sock)
    chunk = view
    while offset < total:
        try:
            sent = sock.send(chunk)
        except OSError as error:
            if error.args[0] == errno.EAGAIN:
                yield write_wait
                continue
            raise
        if sent == 0:
            raise OSError("peer closed during send")
        offset += sent
        chunk = view[offset:]


def recv_until(sock: object, separator: object, *, max_bytes: int) -> bytes:
    """Read from ``sock`` until ``separator`` arrives, and return the bytes through the separator.

    Call it as ``line = yield from recv_until(sock, b"\\r\\n", max_bytes=256)``.
    The helper reads up to 256 bytes at a time.  Bytes that arrive after the
    separator in the same read are dropped.

    Args:
        sock: Connected non-blocking TCP socket.
        separator: Byte string that ends the read, such as ``b"\\r\\n"``.
        max_bytes: Most bytes to collect, so a peer that never sends the
            separator cannot fill memory.

    Yields:
        A ``ReadWait`` on ``sock`` each time no data is waiting.

    Returns:
        The bytes from the start of the read through the first ``separator``.

    Raises:
        OSError: The peer closed before the separator, ``max_bytes`` bytes
            arrived without it, or ``recv_into`` failed with an error other
            than ``EAGAIN``.
        ValueError: ``max_bytes`` is 0 or negative.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    accumulator = bytearray()
    chunk = bytearray(256)
    chunk_view = memoryview(chunk)
    read_wait = ReadWait(sock)
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
        accumulator.extend(chunk_view[:nbytes])
        # Search before enforcing the cap: a chunk that pushes the accumulator
        # past max_bytes may still hold the separator within the cap.
        sep_index = accumulator.find(separator)
        if sep_index != -1 and sep_index + sep_length <= max_bytes:
            return bytes(accumulator[: sep_index + sep_length])
        if len(accumulator) >= max_bytes:
            raise OSError("recv_until exceeded max_bytes")
