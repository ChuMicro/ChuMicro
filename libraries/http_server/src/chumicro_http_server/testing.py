"""Test fakes and builders for ``chumicro-http-server``.

Two host-only helpers for tests that wire ``HttpServer`` against
pre-baked HTTP/1.1 request bytes:

- :class:`FakeListener` — listener stub that hands out queued
  :class:`~chumicro_sockets.testing.FakeSocket` instances on
  ``accept()``.  Raises ``OSError(errno.EAGAIN, "would block")`` when
  the queue is empty so the server's EAGAIN path runs unchanged.
- :func:`request_bytes` — build a raw HTTP/1.1 request byte string
  (start line + optional ``Content-Length`` + extra headers + body).
"""

__chumicro_test_support__ = True


import errno


class FakeListener:
    """Listener stub that hands out queued sockets on ``accept()``.

    Construct with a list of pre-loaded
    :class:`~chumicro_sockets.testing.FakeSocket` instances.  Each
    ``accept()`` call pops the next socket; an empty queue raises
    ``OSError(errno.EAGAIN, "would block")`` matching the EAGAIN shape
    the real listener uses on this host (``11`` on Linux / MP / CP,
    ``35`` on macOS CPython) so the server's would-block handling
    exercises unchanged.
    """

    def __init__(self, connections):
        self._queue = list(connections)
        self._closed = False

    def accept(self):
        if not self._queue:
            raise OSError(errno.EAGAIN, "would block")
        return self._queue.pop(0)

    def close(self):
        self._closed = True

    def setblocking(self, _flag):
        pass


def request_bytes(method="GET", path="/", *, headers=None, body=b""):
    """Build a raw HTTP/1.1 request byte string.

    Args:
        method: Request method (``"GET"``, ``"POST"``, etc.).
        path: Request target including any query string.
        headers: Optional iterable of ``(name, value)`` tuples.
        body: Optional request body.  When non-empty, a
            ``Content-Length`` header is prepended automatically.

    Returns:
        The request as a single ``bytes`` ready to feed to
        :class:`~chumicro_sockets.testing.FakeSocket.enqueue_recv`.
    """
    lines = [f"{method} {path} HTTP/1.1\r\n".encode("ascii")]
    if body:
        lines.append(f"Content-Length: {len(body)}\r\n".encode("ascii"))
    if headers:
        for name, value in headers:
            lines.append(f"{name}: {value}\r\n".encode("ascii"))
    lines.append(b"\r\n")
    if body:
        lines.append(body)
    return b"".join(lines)
