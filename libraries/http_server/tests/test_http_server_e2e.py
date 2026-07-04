"""http_server end-to-end: happy path, protocol error, oversized
body, timeout, EAGAIN paths."""

import errno

from chumicro_http_server import (
    HttpServer,
    build_response,
)
from chumicro_http_server.testing import (
    FakeListener,
    request_bytes,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def _make_server(*, sockets, handler=None, **kwargs):
    """Construct an HttpServer wired to a FakeTicks + a FakeListener."""
    ticks = FakeTicks()
    if handler is None:
        handler = lambda request: build_response(200, text="ok")  # noqa: E731

    listener_called = {"count": 0}

    def transport_factory():
        listener_called["count"] += 1
        return FakeListener(sockets)

    server = HttpServer(
        transport_factory=transport_factory,
        handler=handler,
        ticks=ticks,
        **kwargs,
    )
    return server, ticks, listener_called

def _drive_until_idle(server, ticks, *, max_ticks=200):
    """Tick the server until no in-flight connections remain."""
    for _ in range(max_ticks):
        server.handle(ticks.ticks_ms())
        if server.in_flight == 0:
            return
        ticks.advance(1)
    raise AssertionError(f"server still busy after {max_ticks} ticks")

def _connection(request_bytes):
    """Build a (FakeSocket, peer) tuple from a raw request byte-string."""
    socket = FakeSocket()
    socket.enqueue_recv(request_bytes)
    return socket, ("127.0.0.1", 12345)


class TestHttpServerEndToEnd:
    def test_simple_get_returns_canned_response(self):
        sock, peer = _connection(request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, peer)])
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 200 OK\r\n")
        assert sock.sent.endswith(b"\r\n\r\nok")

    def test_request_object_exposes_method_path_query_body(self):
        captured = {}

        def handler(request):
            captured["method"] = request.method
            captured["path"] = request.path
            captured["query"] = dict(request.query.items())
            captured["headers"] = dict(request.headers.items())
            captured["body"] = request.body
            captured["peer"] = request.peer
            return build_response(200, text="captured")

        sock, peer = _connection(request_bytes(
            method="POST", path="/api?page=2&size=10",
            headers=[("Host", "device.local"), ("X-Custom", "v")],
            body=b"payload",
        ))
        server, ticks, _ = _make_server(sockets=[(sock, peer)], handler=handler)
        _drive_until_idle(server, ticks)
        assert captured["method"] == "POST"
        assert captured["path"] == "/api"
        assert captured["query"] == {"page": "2", "size": "10"}
        assert captured["headers"]["Host"] == "device.local"
        assert captured["headers"]["X-Custom"] == "v"
        assert captured["body"] == b"payload"
        assert captured["peer"] == ("127.0.0.1", 12345)

    def test_handler_returning_json(self):
        def handler(request):
            payload = request.json()
            return build_response(201, json={"received": payload})

        sock, peer = _connection(request_bytes(
            method="POST", path="/data", body=b'{"k": "v"}',
        ))
        server, ticks, _ = _make_server(sockets=[(sock, peer)], handler=handler)
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 201 Created\r\n")
        assert b"Content-Type: application/json\r\n" in sock.sent
        assert b'"received":' in sock.sent

    def test_handler_returning_html(self):
        def handler(request):
            return build_response(200, html="<h1>hi</h1>")

        sock, peer = _connection(request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, peer)], handler=handler)
        _drive_until_idle(server, ticks)
        assert b"Content-Type: text/html; charset=utf-8\r\n" in sock.sent
        assert sock.sent.endswith(b"\r\n\r\n<h1>hi</h1>")

    def test_handler_exception_returns_500(self):
        def handler(_request):
            raise RuntimeError("kaboom")

        sock, peer = _connection(request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, peer)], handler=handler)
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 500 Internal Server Error\r\n")
        assert b"kaboom" in sock.sent

    def test_handler_returning_non_response_raises_500(self):
        def handler(_request):
            return "this is a string, not a Response"

        sock, peer = _connection(request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, peer)], handler=handler)
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 500 Internal Server Error\r\n")
        assert b"expected Response" in sock.sent

    def test_listener_lazy_open(self):
        sock, peer = _connection(request_bytes())
        server, ticks, listener_called = _make_server(sockets=[(sock, peer)])
        assert not server.listening
        assert listener_called["count"] == 0
        server.handle(ticks.ticks_ms())
        assert server.listening
        assert listener_called["count"] == 1

    def test_socket_closed_after_response(self):
        sock, peer = _connection(request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, peer)])
        _drive_until_idle(server, ticks)
        assert sock.closed is True
        assert server.in_flight == 0

    def test_check_returns_true_while_listener_unopened(self):
        """Lazy-open semantics — server reports work pending so the
        runner's first call to handle() opens the listener."""
        sock, peer = _connection(request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, peer)])
        assert server.check(ticks.ticks_ms()) is True

    def test_close_tears_down_listener_and_connections(self):
        sock1, peer1 = _connection(b"GET / HTTP/1.1\r\n")  # incomplete — stalls
        server, ticks, _ = _make_server(sockets=[(sock1, peer1)])
        server.handle(ticks.ticks_ms())  # accept + start parsing
        server.close()
        assert server.listening is False
        assert server.in_flight == 0


class TestHttpServerProtocolError:
    def test_malformed_request_terminates_connection(self):
        sock, peer = _connection(b"NOT-HTTP-AT-ALL\r\n\r\n")
        server, ticks, _ = _make_server(sockets=[(sock, peer)])
        _drive_until_idle(server, ticks)
        assert server.in_flight == 0
        assert sock.closed is True

    def test_socket_error_terminates_connection(self):
        class BrokenSocket(FakeSocket):
            def recv_into(self, _buffer, _nbytes=0):
                raise OSError(99, "boom")

        sock = BrokenSocket()
        sock.enqueue_recv(request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, ("127.0.0.1", 1))])
        _drive_until_idle(server, ticks)
        assert server.in_flight == 0


class TestHttpServerOversizedBody:
    """Content-Length over the cap returns 413 cleanly (no handler
    invocation, no body allocation) and closes the connection.
    """

    def test_oversize_content_length_returns_413(self):
        handler_calls = []

        def handler(request):
            handler_calls.append(request)
            return build_response(200, text="should not reach handler")

        # 50_000 declared body bytes > default 16_384 cap.
        request = (
            b"POST /upload HTTP/1.1\r\n"
            b"Host: device.local\r\n"
            b"Content-Length: 50000\r\n\r\n"
        )
        sock, peer = _connection(request)
        server, ticks, _ = _make_server(sockets=[(sock, peer)], handler=handler)
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 413 Payload Too Large\r\n")
        assert b"50000" in sock.sent  # reported_length surfaces in the body
        assert handler_calls == []
        assert sock.closed is True

    def test_oversize_does_not_drain_body(self):
        # Even when the client started sending body bytes before the
        # server could read headers, the 413 path should not read more
        # than the headers + whatever already sat in the recv buffer.
        # The connection closes; whether the bytes were consumed is a
        # property of the kernel, not us.
        handler_calls = []

        def handler(request):
            handler_calls.append(request)
            return build_response(200, text="should not reach handler")

        request = (
            b"POST /upload HTTP/1.1\r\n"
            b"Host: device.local\r\n"
            b"Content-Length: 50000\r\n\r\n"
            + b"X" * 1000  # client already started sending body bytes
        )
        sock, peer = _connection(request)
        server, ticks, _ = _make_server(sockets=[(sock, peer)], handler=handler)
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 413 Payload Too Large\r\n")
        assert handler_calls == []

    def test_oversize_emits_connection_close(self):
        sock, peer = _connection(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 99999\r\n\r\n",
        )
        server, ticks, _ = _make_server(sockets=[(sock, peer)])
        _drive_until_idle(server, ticks)
        assert b"Connection: close\r\n" in sock.sent

    def test_body_within_cap_runs_handler(self):
        # Negative control: bodies up to max_request_body_bytes still
        # work normally through the standard handler path.
        captured = {}

        def handler(request):
            captured["body"] = request.body
            return build_response(200, text="ok")

        body = b"x" * 2048
        sock, peer = _connection(request_bytes(
            method="POST", path="/upload", body=body,
        ))
        server, ticks, _ = _make_server(
            sockets=[(sock, peer)],
            handler=handler,
            max_request_body_bytes=4096,
        )
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 200 OK\r\n")
        assert captured["body"] == body


class TestHttpServerRequestLineCap:
    """Request line over max_request_line_bytes returns 414 cleanly (no
    handler invocation) and closes the connection.
    """

    def test_oversize_request_line_returns_414(self):
        handler_calls = []

        def handler(request):
            handler_calls.append(request)
            return build_response(200, text="should not reach handler")

        # ~2 KB request-target with no CRLF passes the default 1 KB cap.
        sock, peer = _connection(b"GET /" + b"a" * 2048 + b" HTTP/1.1")
        server, ticks, _ = _make_server(sockets=[(sock, peer)], handler=handler)
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 414 URI Too Long\r\n")
        assert b"Connection: close\r\n" in sock.sent
        assert handler_calls == []
        assert sock.closed is True

    def test_request_line_within_cap_runs_handler(self):
        # Negative control: a long-but-allowed request line still
        # dispatches normally.
        captured = {}

        def handler(request):
            captured["path"] = request.path
            return build_response(200, text="ok")

        sock, peer = _connection(request_bytes(path="/api/" + "x" * 200))
        server, ticks, _ = _make_server(
            sockets=[(sock, peer)],
            handler=handler,
            max_request_line_bytes=512,
        )
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 200 OK\r\n")
        assert captured["path"] == "/api/" + "x" * 200


class TestHttpServerHeadersCap:
    """Header section over max_headers_bytes returns 431 cleanly (no
    handler invocation) and closes the connection.
    """

    def test_oversize_headers_returns_431(self):
        handler_calls = []

        def handler(request):
            handler_calls.append(request)
            return build_response(200, text="should not reach handler")

        request = (
            b"GET / HTTP/1.1\r\n"
            b"X-Big: " + b"v" * 8000 + b"\r\n\r\n"
        )
        sock, peer = _connection(request)
        server, ticks, _ = _make_server(sockets=[(sock, peer)], handler=handler)
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(
            b"HTTP/1.1 431 Request Header Fields Too Large\r\n",
        )
        assert b"Connection: close\r\n" in sock.sent
        assert handler_calls == []
        assert sock.closed is True

    def test_headers_within_cap_run_handler(self):
        captured = {}

        def handler(request):
            captured["host"] = request.headers.get("Host")
            return build_response(200, text="ok")

        sock, peer = _connection(request_bytes(
            headers=[("Host", "device.local"), ("Accept", "*/*")],
        ))
        server, ticks, _ = _make_server(
            sockets=[(sock, peer)],
            handler=handler,
            max_headers_bytes=512,
        )
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 200 OK\r\n")
        assert captured["host"] == "device.local"


class TestHttpServerTimeout:
    def test_connection_dropped_when_deadline_exceeded(self):
        class StalledSocket(FakeSocket):
            def recv_into(self, _buffer, _nbytes=0):
                raise OSError(errno.EAGAIN, "would block")

        sock = StalledSocket()
        server, ticks, _ = _make_server(
            sockets=[(sock, ("127.0.0.1", 1))],
            request_timeout_ms=50,
        )
        for _ in range(60):
            server.handle(ticks.ticks_ms())
            if server.in_flight == 0:
                break
            ticks.advance(2)
        assert server.in_flight == 0
        assert sock.closed is True


class TestHttpServerEagainPaths:
    """Cover the EAGAIN branches in accept + recv + send."""

    def test_accept_eagain_keeps_listener_open(self):
        """When the listener has nothing to accept, the server keeps
        the listener open and doesn't error."""
        server, ticks, _ = _make_server(sockets=[])
        server.handle(ticks.ticks_ms())
        assert server.listening is True
        assert server.in_flight == 0

    def test_send_eagain_resumes_next_tick(self):
        sock = FakeSocket()
        sock.enqueue_recv(request_bytes())
        sock.enqueue_eagain_for_send(2)  # first two sends EAGAIN
        server, ticks, _ = _make_server(sockets=[(sock, ("127.0.0.1", 1))])
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 200 OK\r\n")

    def test_recv_eagain_during_request_resumes(self):
        sock = FakeSocket()
        sock.enqueue_eagain_for_recv(2)
        sock.enqueue_recv(request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, ("127.0.0.1", 1))])
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 200 OK\r\n")
