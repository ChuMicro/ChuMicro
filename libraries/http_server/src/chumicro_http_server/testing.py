"""Test fakes and builders for ``chumicro-http-server``.

The entry points are :class:`FakeListener` and :func:`request_bytes`.
"""

__chumicro_test_support__ = True


import errno


class FakeListener:
    """Listener stub that hands out queued connections on ``accept()``."""

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
        body: Optional request body; a non-empty body auto-adds ``Content-Length``.

    Returns:
        The request as a single ``bytes`` for ``FakeSocket.enqueue_recv``.
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
