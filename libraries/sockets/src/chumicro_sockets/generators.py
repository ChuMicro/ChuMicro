"""Generator helpers for socket I/O driven by a tick-based scheduler.

The public helpers are ``connect``, ``send_all``, ``recv_until``, and ``recv_exact``.
"""

import errno

from chumicro_sockets.waits import ReadWait, WriteWait


def connect(
    connector: object,
    *,
    timeout_ms: int | None = None,
    ticks: object | None = None,
) -> object:
    """Drive *connector* across runner ticks and return its connected socket.

    Args:
        connector: Any object exposing the ``SocketConnector`` surface.
        timeout_ms: Deadline in ms for the whole connect; ``None`` waits indefinitely.
        ticks: ``chumicro_timing``-shaped tick source; required when *timeout_ms* is set.

    Yields:
        The connector itself, repeatedly, until terminal.

    Returns:
        The connected, non-blocking socket; the caller owns its lifecycle.

    Raises:
        OSError: The connector reached ``failed``, or ``ETIMEDOUT`` on timeout.
        ValueError: *timeout_ms* was given without a *ticks* source.
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
            if state == "ready":
                sock = connector.socket
                return sock
            if state == "failed":
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
    """Send every byte of *data*, yielding on ``EAGAIN``.

    Args:
        sock: Non-blocking TCP socket.
        data: Bytes-like object to transmit.

    Yields:
        A ``WriteWait`` carrying *sock* on each ``EAGAIN``.

    Raises:
        OSError: The peer closed mid-send, or the socket reported a non-EAGAIN error.
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
    """Read until *separator* appears; return everything up to and including it.

    Args:
        sock: Non-blocking TCP socket.
        separator: Bytes pattern that terminates the read (for example ``b"\\r\\n"``).
        max_bytes: Hard cap on accumulated bytes, so a peer cannot force an unbounded read.

    Yields:
        A ``ReadWait`` on each ``EAGAIN``.

    Returns:
        ``bytes`` from the start through the first occurrence of *separator*, inclusive.

    Raises:
        OSError: The peer closed before the separator, growth exceeded *max_bytes*, or a non-EAGAIN error.
        ValueError: *max_bytes* is not positive.
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


def recv_exact(sock: object, byte_count: int, *, max_bytes: int) -> bytes:
    """Read exactly *byte_count* bytes and return them as ``bytes``.

    Args:
        sock: Non-blocking TCP socket.
        byte_count: Number of bytes to read. Must be positive.
        max_bytes: Hard cap on the buffer, so a peer-controlled length cannot force an unbounded allocation.

    Yields:
        A ``ReadWait`` on each ``EAGAIN``.

    Returns:
        ``bytes`` of length exactly *byte_count*.

    Raises:
        OSError: The peer closed before *byte_count* bytes arrived, or a non-EAGAIN error.
        ValueError: *byte_count* or *max_bytes* is not positive, or *byte_count* exceeds *max_bytes*.
    """
    if byte_count <= 0:
        raise ValueError("byte_count must be positive")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if byte_count > max_bytes:
        raise ValueError("byte_count exceeds max_bytes")

    buffer = bytearray(byte_count)
    view = memoryview(buffer)
    offset = 0
    read_wait = ReadWait(sock)
    chunk = view

    while offset < byte_count:
        try:
            nbytes = sock.recv_into(chunk)
        except OSError as error:
            if error.args[0] == errno.EAGAIN:
                yield read_wait
                continue
            raise
        if nbytes == 0:
            raise OSError("peer closed before byte_count bytes")
        offset += nbytes
        chunk = view[offset:]

    return bytes(buffer)
