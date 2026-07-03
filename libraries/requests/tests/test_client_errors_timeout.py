"""requests client: busy-error, timeout, error paths."""

import errno

from chumicro_requests import (
    HttpBusyError,
    HttpError,
    HttpProtocolError,
    HttpTimeoutError,
)
from chumicro_requests.testing import (
    canned_response,
    drive_until_done,
    make_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises


class _StalledRecvSocket(FakeSocket):
    """FakeSocket that always raises EAGAIN on recv_into.

    Models a real non-blocking socket that the peer hasn't written
    to — the production-shaped condition that fires per-request
    ``timeout_ms`` budgets.  FakeSocket's default behavior of
    returning 0 on an empty queue is a clean-peer-close signal in
    real socket semantics, which the production client correctly
    treats as end-of-response.
    """

    def recv_into(self, buffer, nbytes=0):
        if self.closed:
            raise OSError(errno.EBADF, "socket closed")
        raise OSError(errno.EAGAIN, "would block")


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
        # No Content-Length means a length-unknown body.  The body
        # ends on a clean peer FIN, which the production client
        # detects via ``recv_into() == 0`` and turns into
        # ``parser.feed_eof()``; the parser then transitions
        # BODY -> DONE.  ``simulate_peer_close`` signals the FIN once
        # the queue drains, matching real non-blocking socket
        # semantics (an empty queue without a FIN raises EAGAIN).
        socket.enqueue_recv(b"HTTP/1.1 200 OK\r\n\r\nstreamed-bytes")
        socket.simulate_peer_close()
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


class SSLWantReadError(OSError):
    """Mimics ssl.SSLWantReadError: an OSError subclass whose errno is
    SSL_ERROR_WANT_READ (2), not EAGAIN."""

    def __init__(self) -> None:
        super().__init__(2, "The operation did not complete (read)")


class TestWouldBlockClassification:
    def test_ssl_want_read_and_ewouldblock_are_would_block(self):
        from chumicro_requests.client import _EWOULDBLOCK, _is_would_block

        assert _is_would_block(SSLWantReadError()) is True
        assert _is_would_block(OSError(errno.EAGAIN, "again")) is True
        assert _is_would_block(OSError(_EWOULDBLOCK, "wouldblock")) is True

    def test_genuine_socket_error_is_not_would_block(self):
        from chumicro_requests.client import _is_would_block

        assert _is_would_block(OSError(errno.ECONNRESET, "reset")) is False
