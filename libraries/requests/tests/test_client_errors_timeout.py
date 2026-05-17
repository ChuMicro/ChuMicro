"""requests client: busy-error, timeout, error paths."""

from chumicro_requests import (
    HttpBusyError,
    HttpClient,
    HttpError,
    HttpProtocolError,
    HttpTimeoutError,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks


def make_factory(socket_or_factory):
    """Return a connection_factory that hands out *socket_or_factory*.

    *socket_or_factory* can be either a single :class:`FakeSocket`
    (returned every call) or a zero-arg callable that builds a fresh
    one on demand.
    """
    def factory(host, port, use_tls):  # noqa: ARG001 — fake ignores args
        if callable(socket_or_factory):
            return socket_or_factory()
        return socket_or_factory

    return factory

def canned_response(*, status=200, reason="OK", body=b"", extra_headers=()):
    """Build an HTTP/1.1 response byte-string with Content-Length."""
    lines = [f"HTTP/1.1 {status} {reason}\r\n".encode("ascii")]
    lines.append(f"Content-Length: {len(body)}\r\n".encode("ascii"))
    lines.append(b"Content-Type: text/plain\r\n")
    for name, value in extra_headers:
        lines.append(f"{name}: {value}\r\n".encode("ascii"))
    lines.append(b"\r\n")
    lines.append(body)
    return b"".join(lines)

def drive_until_done(client, handle, ticks, *, max_ticks=200, advance_ms=1):
    """Run handle/check until done; safety-cap at *max_ticks* iterations."""
    for _ in range(max_ticks):
        if handle.done:
            return
        if client.check(ticks.ticks_ms()):
            client.handle(ticks.ticks_ms())
        ticks.advance(advance_ms)
    raise AssertionError(f"handle never completed within {max_ticks} ticks")

def make_client(*, socket_or_factory=None, **kwargs):
    """Construct an HttpClient wired to FakeTicks + a FakeSocket factory."""
    ticks = FakeTicks()
    socket = socket_or_factory if socket_or_factory is not None else FakeSocket()
    client = HttpClient(
        connection_factory=make_factory(socket),
        ticks=ticks,
        **kwargs,
    )
    return client, ticks, socket

class _StalledRecvSocket(FakeSocket):
    """FakeSocket that always raises EAGAIN on recv_into.

    Models a real non-blocking socket that the peer hasn't written
    to — the production-shaped condition that fires per-request
    ``timeout_ms`` budgets.  FakeSocket's default behavior of
    returning 0 on an empty queue is a clean-peer-close signal in
    real socket semantics, which the production client correctly
    treats as end-of-response.  This subclass is the right fixture
    for "stalled connection" tests.
    """

    def recv_into(self, buffer, nbytes=0):
        if self._closed:
            raise OSError(9, "socket closed")
        raise OSError(11, "would block")


class TestHttpClientBusyError:
    """A second request while one is in flight raises HttpBusyError."""

    def test_second_get_during_recv_raises(self):
        socket = FakeSocket()  # no response queued — request will hang
        client, _ticks, _ = make_client(socket_or_factory=socket)
        client.get("http://example.test/one")
        with raises(HttpBusyError, match="busy"):
            client.get("http://example.test/two")

    def test_can_issue_after_completion(self):
        # Two FakeSockets, returned in sequence.
        sockets = [FakeSocket(), FakeSocket()]
        sockets[0].enqueue_recv(canned_response(body=b"first"))
        sockets[1].enqueue_recv(canned_response(body=b"second"))
        index = {"position": 0}

        def factory_callable():
            socket = sockets[index["position"]]
            index["position"] += 1
            return socket

        client, ticks, _ = make_client(socket_or_factory=factory_callable)

        first = client.get("http://example.test/one")
        drive_until_done(client, first, ticks)
        assert first.result.body == b"first"

        second = client.get("http://example.test/two")
        drive_until_done(client, second, ticks)
        assert second.result.body == b"second"


class TestHttpClientTimeout:
    """Per-request ``timeout_ms`` fails the request when expired."""

    def test_timeout_fires_when_no_response(self):
        socket = _StalledRecvSocket()
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/", timeout_ms=50)
        for _ in range(60):
            if handle.done:
                break
            client.handle(ticks.ticks_ms())
            ticks.advance(2)
        assert handle.done is True
        assert isinstance(handle.error, HttpTimeoutError)
        with raises(HttpTimeoutError):
            _ = handle.result

    def test_default_timeout_used_when_none(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"ok"))
        client, ticks, _ = make_client(
            socket_or_factory=socket, default_timeout_ms=100,
        )
        handle = client.get("http://example.test/")  # no per-call timeout_ms
        drive_until_done(client, handle, ticks)
        assert handle.result.body == b"ok"


class TestHttpClientErrors:
    """Socket / protocol errors propagate to the handle."""

    def test_protocol_error_fails_handle(self):
        socket = FakeSocket()
        socket.enqueue_recv(b"BROKEN-NOT-HTTP\r\n")
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert isinstance(handle.error, HttpProtocolError)

    def test_socket_error_fails_handle(self):
        class BrokenSocket(FakeSocket):
            def send(self, data):
                raise OSError(99, "boom")

        socket = BrokenSocket()
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert isinstance(handle.error, HttpError)
        assert "socket error" in str(handle.error)

    def test_send_eagain_retries_next_tick(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"hi"))
        socket.enqueue_eagain_for_send(2)  # first two send calls return EAGAIN
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert handle.result.body == b"hi"

    def test_recv_eagain_during_response_retries(self):
        socket = FakeSocket()
        socket.enqueue_eagain_for_recv(2)
        socket.enqueue_recv(canned_response(body=b"yo"))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert handle.result.body == b"yo"

    def test_peer_close_completes_unknown_length_body(self):
        socket = FakeSocket()
        # No Content-Length → length-unknown body.  FakeSocket returns
        # 0 once the recv queue drains, which mirrors a clean peer
        # close — the production client calls feed_eof() and the
        # parser transitions BODY -> DONE.
        socket.enqueue_recv(b"HTTP/1.1 200 OK\r\n\r\nstreamed-bytes")
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert handle.result.body == b"streamed-bytes"

    def test_result_before_done_raises(self):
        socket = FakeSocket()
        client, _ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        with raises(HttpError, match="before done"):
            _ = handle.result
