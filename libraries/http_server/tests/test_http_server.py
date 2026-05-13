"""Tests for chumicro_http_server — listener + parser + canned response.

HttpServer is runner-shaped (check / handle): each connection is a
state machine advanced one chunk per tick, with a single
caller-provided handler.

These tests use a fake listener that hands out :class:`FakeSocket`
pre-loaded with the request bytes — the server thinks it accepted a
real connection, parses the request, runs the handler, writes the
response back to the FakeSocket's `sent` buffer where tests assert.
"""

from chumicro_http_server import (
    CaseInsensitiveDict,
    HttpServer,
    RequestParser,
    RequestParseState,
    ServerProtocolError,
    build_response,
    encode_response,
    parse_charset,
    parse_query,
    split_target,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeListener:
    """Listener stub that hands out queued FakeSockets on accept()."""

    def __init__(self, connections):
        self._queue = list(connections)
        self._closed = False

    def accept(self):
        if not self._queue:
            raise OSError(11, "would block")
        return self._queue.pop(0)

    def close(self):
        self._closed = True

    def setblocking(self, _flag):
        pass


def _request_bytes(method="GET", path="/", *, headers=None, body=b""):
    """Build a raw HTTP/1.1 request byte-string."""
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


def _make_server(*, sockets, handler=None, **kwargs):
    """Construct an HttpServer wired to a FakeTicks + a _FakeListener."""
    ticks = FakeTicks()
    if handler is None:
        handler = lambda request: build_response(200, text="ok")  # noqa: E731

    listener_called = {"count": 0}

    def listener_factory():
        listener_called["count"] += 1
        return _FakeListener(sockets)

    server = HttpServer(
        listener_factory=listener_factory,
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


def _drive_until_all_responded(server, ticks, sockets, *, max_ticks=400):
    """Drive until every socket in *sockets* has been closed by the server.

    Necessary for multi-connection tests because the server accepts
    one new connection per tick — single-connection ``_drive_until_idle``
    exits the moment the first connection finishes, leaving any
    queued-but-not-yet-accepted sockets behind.
    """
    for _ in range(max_ticks):
        server.handle(ticks.ticks_ms())
        if all(sock.closed for sock in sockets):
            return
        ticks.advance(1)
    raise AssertionError(
        f"not all sockets responded after {max_ticks} ticks; "
        f"closed = {[sock.closed for sock in sockets]}",
    )


# ---------------------------------------------------------------------------
# Request-target helpers
# ---------------------------------------------------------------------------


class TestSplitTarget:
    def test_path_only(self):
        assert split_target("/") == ("/", "")

    def test_path_with_query(self):
        assert split_target("/api?k=v") == ("/api", "k=v")

    def test_path_with_query_and_multiple_params(self):
        assert split_target("/x?a=1&b=2") == ("/x", "a=1&b=2")

    def test_question_mark_only(self):
        assert split_target("/?") == ("/", "")


class TestParseQuery:
    def test_empty(self):
        assert len(parse_query("")) == 0

    def test_single_pair(self):
        result = parse_query("k=v")
        assert result["k"] == "v"

    def test_multiple_pairs(self):
        result = parse_query("a=1&b=2")
        assert result["a"] == "1"
        assert result["b"] == "2"

    def test_value_less_param(self):
        result = parse_query("flag")
        assert result["flag"] == ""

    def test_empty_pair_skipped(self):
        result = parse_query("a=1&&b=2")
        assert result["a"] == "1"
        assert result["b"] == "2"

    def test_repeated_keys_join(self):
        result = parse_query("k=1&k=2")
        assert result["k"] == "1, 2"


# ---------------------------------------------------------------------------
# RequestParser
# ---------------------------------------------------------------------------


class TestRequestParser:
    def test_simple_get(self):
        parser = RequestParser()
        parser.feed(_request_bytes(method="GET", path="/api"))
        assert parser.state == RequestParseState.DONE
        assert parser.method == "GET"
        assert parser.target == "/api"
        assert parser.http_version == "HTTP/1.1"

    def test_request_with_body(self):
        parser = RequestParser()
        parser.feed(_request_bytes(method="POST", path="/", body=b"hello"))
        assert parser.state == RequestParseState.DONE
        assert parser.body == b"hello"

    def test_request_split_across_feeds(self):
        parser = RequestParser()
        full = _request_bytes(method="POST", path="/", body=b"world")
        for byte_index in range(len(full)):
            parser.feed(full[byte_index:byte_index + 1])
        assert parser.state == RequestParseState.DONE
        assert parser.body == b"world"

    def test_headers_preserved_case_insensitive(self):
        parser = RequestParser()
        parser.feed(_request_bytes(
            headers=[("Host", "example.test"), ("X-Custom", "value")],
        ))
        assert parser.headers["host"] == "example.test"
        assert parser.headers["X-CUSTOM"] == "value"

    def test_malformed_request_line_two_parts(self):
        parser = RequestParser()
        parser.feed(b"GET /\r\n")
        assert parser.state == RequestParseState.ERROR
        assert isinstance(parser.error, ServerProtocolError)

    def test_request_line_missing_http_prefix(self):
        parser = RequestParser()
        parser.feed(b"GET / NOT-HTTP/1.1\r\n")
        assert parser.state == RequestParseState.ERROR

    def test_empty_method(self):
        parser = RequestParser()
        parser.feed(b" / HTTP/1.1\r\n")
        assert parser.state == RequestParseState.ERROR

    def test_empty_target(self):
        parser = RequestParser()
        parser.feed(b"GET  HTTP/1.1\r\n")
        assert parser.state == RequestParseState.ERROR

    def test_negative_content_length(self):
        parser = RequestParser()
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: -5\r\n\r\n",
        )
        assert parser.state == RequestParseState.ERROR

    def test_non_integer_content_length(self):
        parser = RequestParser()
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: lots\r\n\r\n",
        )
        assert parser.state == RequestParseState.ERROR

    def test_oversized_content_length(self):
        parser = RequestParser(max_body_bytes=10)
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 9999\r\n\r\n",
        )
        assert parser.state == RequestParseState.ERROR

    def test_zero_content_length_completes(self):
        parser = RequestParser()
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 0\r\n\r\n",
        )
        assert parser.state == RequestParseState.DONE
        assert parser.body == b""

    def test_no_content_length_means_no_body(self):
        parser = RequestParser()
        parser.feed(b"GET / HTTP/1.1\r\n\r\n")
        assert parser.state == RequestParseState.DONE

    def test_header_missing_colon(self):
        parser = RequestParser()
        parser.feed(
            b"GET / HTTP/1.1\r\n"
            b"NoColon\r\n\r\n",
        )
        assert parser.state == RequestParseState.ERROR

    def test_eof_mid_headers_protocol_error(self):
        parser = RequestParser()
        parser.feed(b"GET / HTTP/1.1\r\nHost: x")
        parser.feed_eof()
        assert parser.state == RequestParseState.ERROR

    def test_eof_mid_body_protocol_error(self):
        parser = RequestParser()
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 100\r\n\r\n"
            b"short",
        )
        parser.feed_eof()
        assert parser.state == RequestParseState.ERROR


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------


class TestBuildResponse:
    def test_default_200(self):
        response = build_response()
        assert response.status_code == 200
        assert response.reason == "OK"
        assert response.body == b""

    def test_text_default_content_type(self):
        response = build_response(200, text="hello")
        assert response.body == b"hello"
        assert response.headers["Content-Type"] == "text/plain; charset=utf-8"

    def test_html_default_content_type(self):
        response = build_response(200, html="<h1>Hi</h1>")
        assert response.body == b"<h1>Hi</h1>"
        assert response.headers["Content-Type"] == "text/html; charset=utf-8"

    def test_json_default_content_type(self):
        response = build_response(200, json={"k": "v"})
        assert response.body == b'{"k": "v"}'
        assert response.headers["Content-Type"] == "application/json"

    def test_bytes_body_no_default_content_type(self):
        response = build_response(200, body=b"\x00\x01\x02")
        assert response.body == b"\x00\x01\x02"
        assert "Content-Type" not in response.headers

    def test_str_body_encoded_utf8_no_default_content_type(self):
        response = build_response(200, body="hello")
        assert response.body == b"hello"

    def test_caller_headers_override_default(self):
        response = build_response(
            200, json={"k": "v"},
            headers={"Content-Type": "application/vnd.custom+json"},
        )
        assert response.headers["Content-Type"] == "application/vnd.custom+json"

    def test_multiple_body_kwargs_rejected(self):
        with raises(ValueError, match="at most one"):
            build_response(200, body=b"x", json={"k": "v"})

    def test_non_bytes_str_body_rejected(self):
        with raises(TypeError, match="bytes / bytearray / str"):
            build_response(200, body=42)

    def test_unknown_status_uses_unknown_reason(self):
        response = build_response(599)
        assert response.reason == "Unknown"

    def test_iterable_headers_input(self):
        response = build_response(
            200, text="ok",
            headers=[("X-Custom", "v")],
        )
        assert response.headers["X-Custom"] == "v"


class TestEncodeResponse:
    def test_encodes_status_headers_body(self):
        response = build_response(200, text="hello")
        wire = encode_response(response)
        assert wire.startswith(b"HTTP/1.1 200 OK\r\n")
        assert b"Content-Length: 5\r\n" in wire
        assert b"Content-Type: text/plain; charset=utf-8\r\n" in wire
        assert b"Connection: close\r\n" in wire
        assert wire.endswith(b"\r\n\r\nhello")

    def test_empty_body_zero_content_length(self):
        response = build_response(204)
        wire = encode_response(response)
        assert b"Content-Length: 0\r\n" in wire
        assert wire.endswith(b"\r\n\r\n")


# ---------------------------------------------------------------------------
# HttpServer end-to-end
# ---------------------------------------------------------------------------


def _connection(request_bytes):
    """Build a (FakeSocket, peer) tuple from a raw request byte-string."""
    socket = FakeSocket()
    socket.enqueue_recv(request_bytes)
    return socket, ("127.0.0.1", 12345)


class TestHttpServerEndToEnd:
    def test_simple_get_returns_canned_response(self):
        sock, peer = _connection(_request_bytes())
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

        sock, peer = _connection(_request_bytes(
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

        sock, peer = _connection(_request_bytes(
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

        sock, peer = _connection(_request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, peer)], handler=handler)
        _drive_until_idle(server, ticks)
        assert b"Content-Type: text/html; charset=utf-8\r\n" in sock.sent
        assert sock.sent.endswith(b"\r\n\r\n<h1>hi</h1>")

    def test_handler_exception_returns_500(self):
        def handler(_request):
            raise RuntimeError("kaboom")

        sock, peer = _connection(_request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, peer)], handler=handler)
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 500 Internal Server Error\r\n")
        assert b"kaboom" in sock.sent

    def test_handler_returning_non_response_raises_500(self):
        def handler(_request):
            return "this is a string, not a Response"

        sock, peer = _connection(_request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, peer)], handler=handler)
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 500 Internal Server Error\r\n")
        assert b"expected Response" in sock.sent

    def test_listener_lazy_open(self):
        sock, peer = _connection(_request_bytes())
        server, ticks, listener_called = _make_server(sockets=[(sock, peer)])
        assert not server.listening
        assert listener_called["count"] == 0
        server.handle(ticks.ticks_ms())
        assert server.listening
        assert listener_called["count"] == 1

    def test_socket_closed_after_response(self):
        sock, peer = _connection(_request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, peer)])
        _drive_until_idle(server, ticks)
        assert sock.closed is True
        assert server.in_flight == 0

    def test_check_returns_true_while_listener_unopened(self):
        """Lazy-open semantics — server reports work pending so the
        runner's first call to handle() opens the listener."""
        sock, peer = _connection(_request_bytes())
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
        sock.enqueue_recv(_request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, ("127.0.0.1", 1))])
        _drive_until_idle(server, ticks)
        assert server.in_flight == 0


class TestHttpServerTimeout:
    def test_connection_dropped_when_deadline_exceeded(self):
        class StalledSocket(FakeSocket):
            def recv_into(self, _buffer, _nbytes=0):
                raise OSError(11, "would block")

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
        sock.enqueue_recv(_request_bytes())
        sock.enqueue_eagain_for_send(2)  # first two sends EAGAIN
        server, ticks, _ = _make_server(sockets=[(sock, ("127.0.0.1", 1))])
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 200 OK\r\n")

    def test_recv_eagain_during_request_resumes(self):
        sock = FakeSocket()
        sock.enqueue_eagain_for_recv(2)
        sock.enqueue_recv(_request_bytes())
        server, ticks, _ = _make_server(sockets=[(sock, ("127.0.0.1", 1))])
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 200 OK\r\n")


class TestHttpServerInFlightObservation:
    def test_in_flight_increments_after_accept(self):
        # Use a stalled socket so the connection sticks around.
        sock_stalled = type("Stalled", (FakeSocket,), {
            "recv_into": lambda self, _b, _n=0: (_ for _ in ()).throw(OSError(11, "would block")),
        })()
        server, ticks, _ = _make_server(sockets=[(sock_stalled, ("127.0.0.1", 1))])
        assert server.in_flight == 0
        server.handle(ticks.ticks_ms())
        assert server.in_flight == 1
        server.close()


class TestEncodeResponseAcceptsCallerHeaders:
    """Caller-supplied headers in encode_response come through."""

    def test_caller_headers_dict(self):
        from chumicro_http_server import Response
        response = Response(
            status_code=200, reason="OK",
            headers={"X-Custom": "v"},
            body=b"hi",
        )
        wire = encode_response(response)
        assert b"X-Custom: v\r\n" in wire

    def test_caller_headers_caseinsensitive_dict(self):
        from chumicro_http_server import CaseInsensitiveDict, Response
        headers = CaseInsensitiveDict()
        headers["X-Custom"] = "v"
        response = Response(
            status_code=200, reason="OK",
            headers=headers,
            body=b"hi",
        )
        wire = encode_response(response)
        assert b"X-Custom: v\r\n" in wire

    def test_caller_headers_iterable(self):
        from chumicro_http_server import Response
        response = Response(
            status_code=200, reason="OK",
            headers=[("X-Custom", "v")],
            body=b"hi",
        )
        wire = encode_response(response)
        assert b"X-Custom: v\r\n" in wire


class TestRequestObject:
    """Request value-object methods."""

    def test_text_decodes_utf8(self):
        from chumicro_http_server import CaseInsensitiveDict, Request
        request = Request(
            method="POST", target="/", http_version="HTTP/1.1",
            headers=CaseInsensitiveDict(),
            body="café".encode(),
            peer=("127.0.0.1", 1),
        )
        assert request.text() == "café"

    def test_json_decodes(self):
        from chumicro_http_server import CaseInsensitiveDict, Request
        request = Request(
            method="POST", target="/", http_version="HTTP/1.1",
            headers=CaseInsensitiveDict(),
            body=b'{"k": "v"}',
            peer=("127.0.0.1", 1),
        )
        assert request.json() == {"k": "v"}

    def test_repr_includes_method_target_peer(self):
        from chumicro_http_server import CaseInsensitiveDict, Request
        request = Request(
            method="GET", target="/api", http_version="HTTP/1.1",
            headers=CaseInsensitiveDict(),
            body=b"",
            peer=("10.0.0.5", 54321),
        )
        text = repr(request)
        assert "GET" in text
        assert "/api" in text
        assert "10.0.0.5" in text

    def test_response_repr(self):
        from chumicro_http_server import CaseInsensitiveDict, Response
        response = Response(
            status_code=200, reason="OK",
            headers=CaseInsensitiveDict(),
            body=b"hello",
        )
        text = repr(response)
        assert "200" in text
        assert "5 bytes" in text


class TestHttpServerRouting:
    """``@server.route`` decorator + two-dict router (slice 7b)."""

    def _route_server(self, sockets, **kwargs):
        ticks = FakeTicks()
        server = HttpServer(
            listener_factory=lambda: _FakeListener(sockets),
            ticks=ticks,
            **kwargs,
        )
        return server, ticks

    def test_route_decorator_registers_handler(self):
        sock, peer = _connection(_request_bytes(method="GET", path="/api"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/api")
        def index(request):
            return build_response(200, text=f"hello-{request.method}")

        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 200 OK\r\n")
        assert sock.sent.endswith(b"\r\n\r\nhello-GET")

    def test_route_default_method_is_get(self):
        sock_get, peer_get = _connection(_request_bytes(method="GET", path="/x"))
        sock_post, peer_post = _connection(_request_bytes(method="POST", path="/x"))
        server, ticks = self._route_server([
            (sock_get, peer_get), (sock_post, peer_post),
        ])

        @server.route("/x")  # default methods=("GET",)
        def handler_x(request):
            return build_response(200, text="ok")

        _drive_until_all_responded(server, ticks, [sock_get, sock_post])
        # GET succeeds.
        assert sock_get.sent.startswith(b"HTTP/1.1 200 OK\r\n")
        # POST hits 405 with Allow header.
        assert sock_post.sent.startswith(b"HTTP/1.1 405 Method Not Allowed\r\n")
        assert b"Allow: GET\r\n" in sock_post.sent

    def test_route_multi_method(self):
        sock_get, peer_get = _connection(_request_bytes(method="GET", path="/api"))
        sock_post, peer_post = _connection(_request_bytes(method="POST", path="/api"))
        server, ticks = self._route_server([
            (sock_get, peer_get), (sock_post, peer_post),
        ])

        @server.route("/api", methods=["GET", "POST"])
        def api(request):
            return build_response(200, text=request.method)

        _drive_until_all_responded(server, ticks, [sock_get, sock_post])
        assert sock_get.sent.endswith(b"\r\n\r\nGET")
        assert sock_post.sent.endswith(b"\r\n\r\nPOST")

    def test_path_param_extraction(self):
        sock, peer = _connection(_request_bytes(method="GET", path="/widgets/42"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/widgets/<id>")
        def widget(request):
            return build_response(200, text=f"id={request.path_params['id']}")

        _drive_until_idle(server, ticks)
        assert sock.sent.endswith(b"\r\n\r\nid=42")

    def test_path_param_with_query_string(self):
        sock, peer = _connection(
            _request_bytes(method="GET", path="/widgets/abc?fields=name"),
        )
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/widgets/<id>")
        def widget(request):
            assert request.query["fields"] == "name"
            return build_response(200, text=request.path_params["id"])

        _drive_until_idle(server, ticks)
        assert sock.sent.endswith(b"\r\n\r\nabc")

    def test_unrouted_path_returns_404(self):
        sock, peer = _connection(_request_bytes(method="GET", path="/nope"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/api")
        def api(_request):
            return build_response(200)

        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 404 Not Found\r\n")

    def test_method_not_allowed_returns_405_with_allow_header(self):
        sock, peer = _connection(_request_bytes(method="DELETE", path="/api"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/api", methods=["GET", "POST"])
        def api(_request):
            return build_response(200)

        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 405 Method Not Allowed\r\n")
        # Allow header lists both registered methods (sorted).
        assert b"Allow: GET, POST\r\n" in sock.sent

    def test_method_not_allowed_for_pattern_route(self):
        sock, peer = _connection(_request_bytes(method="DELETE", path="/widgets/42"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/widgets/<id>", methods=["GET"])
        def widget(_request):
            return build_response(200)

        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 405 Method Not Allowed\r\n")
        assert b"Allow: GET\r\n" in sock.sent

    def test_fallback_handler_used_when_no_route_matches(self):
        sock, peer = _connection(_request_bytes(method="GET", path="/anywhere"))
        server, ticks = self._route_server(
            [(sock, peer)],
            handler=lambda request: build_response(
                200, text=f"fallback-{request.path}",
            ),
        )

        @server.route("/api")
        def api(_request):
            return build_response(200, text="api")

        _drive_until_idle(server, ticks)
        assert sock.sent.endswith(b"\r\n\r\nfallback-/anywhere")

    def test_explicit_route_takes_precedence_over_fallback(self):
        sock, peer = _connection(_request_bytes(method="GET", path="/api"))
        server, ticks = self._route_server(
            [(sock, peer)],
            handler=lambda _r: build_response(200, text="fallback"),
        )

        @server.route("/api")
        def api(_request):
            return build_response(200, text="explicit")

        _drive_until_idle(server, ticks)
        assert sock.sent.endswith(b"\r\n\r\nexplicit")

    def test_no_handler_no_routes_returns_404(self):
        sock, peer = _connection(_request_bytes())
        server, ticks = self._route_server([(sock, peer)])
        # No @route, no fallback handler.
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 404 Not Found\r\n")

    def test_re_register_overrides_previous_handler(self):
        sock, peer = _connection(_request_bytes(method="GET", path="/x"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/x")
        def first(_request):
            return build_response(200, text="first")  # pragma: no cover

        @server.route("/x")
        def second(_request):
            return build_response(200, text="second")

        _drive_until_idle(server, ticks)
        assert sock.sent.endswith(b"\r\n\r\nsecond")

    def test_re_register_pattern_route_overrides(self):
        sock, peer = _connection(_request_bytes(method="GET", path="/items/x"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/items/<id>")
        def first(_request):
            return build_response(200, text="first")  # pragma: no cover

        @server.route("/items/<id>")
        def second(_request):
            return build_response(200, text="second")

        _drive_until_idle(server, ticks)
        assert sock.sent.endswith(b"\r\n\r\nsecond")

    def test_method_uppercase_normalized(self):
        sock, peer = _connection(_request_bytes(method="POST", path="/api"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/api", methods=["post"])  # lowercase
        def api(_request):
            return build_response(201, text="ok")

        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 201 Created\r\n")


class TestHttpServerRespondMethod:
    """``HttpServer.respond`` mirrors the module-level builder."""

    def test_instance_method_works(self):
        server, ticks, _ = _make_server(sockets=[])
        response = server.respond(200, text="hi")
        assert response.body == b"hi"
        assert response.headers["Content-Type"] == "text/plain; charset=utf-8"


class TestHttpServerAcceptVariants:
    """Listeners that return None vs raise EAGAIN are both supported."""

    def test_accept_returning_none_is_skipped(self):
        """Some adapters return None instead of raising EAGAIN."""
        class NoneListener:
            def accept(self):
                return None
            def close(self):
                pass
            def setblocking(self, _flag):
                pass

        ticks = FakeTicks()
        server = HttpServer(
            listener_factory=lambda: NoneListener(),
            handler=lambda request: build_response(200),
            ticks=ticks,
        )
        server.handle(ticks.ticks_ms())
        assert server.in_flight == 0
        assert server.listening is True


class TestRequestParserBodyStateTransition:
    """Exercise the parser state map's BODY branch via partial body."""

    def test_partial_body_keeps_connection_in_want_body(self):
        sock = FakeSocket()
        # Send headers + half the body, then nothing more; connection
        # should sit in WANT_BODY until either more data or timeout.
        request_head = (
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 100\r\n\r\n"
            b"x" * 50
        )
        sock.enqueue_recv(request_head)
        sock.enqueue_eagain_for_recv(100)  # keep stalled

        ticks = FakeTicks()
        server = HttpServer(
            listener_factory=lambda: _FakeListener([(sock, ("127.0.0.1", 1))]),
            handler=lambda request: build_response(200),
            request_timeout_ms=1_000_000,  # don't time out
            ticks=ticks,
        )
        # Drive a few ticks; connection should be stalled mid-body, not done.
        for _ in range(5):
            server.handle(ticks.ticks_ms())
            ticks.advance(1)
        assert server.in_flight == 1
        # Cleanup
        server.close()


# ---------------------------------------------------------------------------
# Inlined shared primitives — CaseInsensitiveDict + parse_charset
#
# These were imported from chumicro-requests pre-decoupling; now inlined
# (see chumicro_http_server/_wire.py).  Tests mirror the chumicro-requests
# suite to lock the byte-for-byte equivalence in.
# ---------------------------------------------------------------------------


class TestParseCharset:
    """``parse_charset`` extracts ``charset=`` from Content-Type values."""

    def test_no_header_defaults_utf8(self):
        assert parse_charset(None) == "utf-8"

    def test_empty_header_defaults_utf8(self):
        assert parse_charset("") == "utf-8"

    def test_charset_explicit(self):
        assert parse_charset("text/html; charset=utf-8") == "utf-8"

    def test_charset_quoted(self):
        assert parse_charset('text/html; charset="ISO-8859-1"') == "ISO-8859-1"

    def test_charset_uppercase_token(self):
        assert parse_charset("text/html; CHARSET=latin-1") == "latin-1"

    def test_no_charset_param_defaults_utf8(self):
        assert parse_charset("application/json") == "utf-8"

    def test_charset_after_other_params(self):
        result = parse_charset("text/html; boundary=x; charset=cp1252")
        assert result == "cp1252"

    def test_blank_charset_value_defaults_utf8(self):
        assert parse_charset("text/plain; charset=") == "utf-8"


class TestCaseInsensitiveDict:
    """Header lookups fold case; original casing preserved on iteration."""

    def test_set_and_get(self):
        headers = CaseInsensitiveDict()
        headers["Content-Type"] = "text/plain"
        assert headers["content-type"] == "text/plain"
        assert headers["CONTENT-TYPE"] == "text/plain"

    def test_contains(self):
        headers = CaseInsensitiveDict()
        headers["X-Foo"] = "bar"
        assert "x-foo" in headers
        assert "X-FOO" in headers
        assert "missing" not in headers

    def test_iter_preserves_original_case(self):
        headers = CaseInsensitiveDict()
        headers["Content-Type"] = "text/plain"
        headers["X-Custom-Header"] = "v"
        assert list(headers) == ["Content-Type", "X-Custom-Header"]

    def test_len(self):
        headers = CaseInsensitiveDict()
        assert len(headers) == 0
        headers["a"] = "1"
        headers["B"] = "2"
        assert len(headers) == 2

    def test_get_default(self):
        headers = CaseInsensitiveDict()
        assert headers.get("missing") is None
        assert headers.get("missing", "fallback") == "fallback"

    def test_items(self):
        headers = CaseInsensitiveDict()
        headers["A"] = "1"
        headers["B"] = "2"
        assert list(headers.items()) == [("A", "1"), ("B", "2")]

    def test_add_appends_with_join(self):
        """RFC 7230 §3.2.2: repeated header lines join with ``, ``."""
        headers = CaseInsensitiveDict()
        headers.add("Set-Cookie", "session=abc")
        headers.add("Set-Cookie", "tracker=xyz")
        assert headers["set-cookie"] == "session=abc, tracker=xyz"

    def test_add_then_setitem_overrides(self):
        headers = CaseInsensitiveDict()
        headers.add("X-Foo", "first")
        headers["x-foo"] = "second"
        assert headers["X-Foo"] == "second"

    def test_add_new_key_behaves_like_setitem(self):
        headers = CaseInsensitiveDict()
        headers.add("X-Solo", "value")
        assert headers["x-solo"] == "value"

    def test_equality_same_keys_and_values(self):
        first = CaseInsensitiveDict()
        first["A"] = "1"
        second = CaseInsensitiveDict()
        second["a"] = "1"
        assert first == second

    def test_equality_different_lengths(self):
        first = CaseInsensitiveDict()
        first["A"] = "1"
        second = CaseInsensitiveDict()
        second["A"] = "1"
        second["B"] = "2"
        assert first != second

    def test_equality_different_values(self):
        first = CaseInsensitiveDict()
        first["A"] = "1"
        second = CaseInsensitiveDict()
        second["A"] = "2"
        assert first != second

    def test_equality_different_keys(self):
        first = CaseInsensitiveDict()
        first["A"] = "1"
        second = CaseInsensitiveDict()
        second["B"] = "1"
        assert first != second

    def test_equality_against_non_dict(self):
        headers = CaseInsensitiveDict()
        # NotImplemented → Python falls back; against a plain dict
        # both sides return NotImplemented and Python settles on False.
        assert headers != {"a": 1}

    def test_repr_round_trip_keys(self):
        headers = CaseInsensitiveDict()
        headers["A"] = "1"
        headers["B"] = "2"
        text = repr(headers)
        assert "A" in text and "B" in text


# ---------------------------------------------------------------------------
# from_config — config-aware construction
# ---------------------------------------------------------------------------


class TestFromConfig:
    """``HttpServer.from_config`` reads the manifest's optional keys
    with sensible fall-back defaults.  Like ntp / requests / websockets
    (and unlike mqtt), no key is required — the auto-built listener
    factory binds to ``0.0.0.0:8080`` when nothing is configured.

    TLS is opt-in and requires *both* ``tls.cert_path`` and
    ``tls.key_path``: a single half raises ``MissingConfigKey`` so a
    half-configured TLS deploy fails loudly instead of silently
    dropping into plain TCP."""

    def test_reads_all_non_tls_keys(self) -> None:
        """A complete config dict populates every non-TLS manifest key."""
        config = {
            "http_server.bind_host": "127.0.0.1",
            "http_server.bind_port": 9090,
            "http_server.max_connections": 8,
            "http_server.request_timeout_ms": 30_000,
            "http_server.max_request_body_bytes": 64_000,
        }
        # listener_factory= bypasses the host/port-driven auto-build,
        # so we can assert the constructor knobs without touching
        # chumicro_sockets.
        server = HttpServer.from_config(
            config, listener_factory=lambda: _FakeListener([]),
        )
        assert server._max_connections == 8  # noqa: SLF001
        assert server._request_timeout_ms == 30_000  # noqa: SLF001
        assert server._max_request_body_bytes == 64_000  # noqa: SLF001

    def test_defaults_apply_when_keys_absent(self) -> None:
        """Empty config dict → every manifest key falls back to its default.

        Documents the asymmetry vs ``MQTTClient.from_config``: empty
        config is valid input — the auto-built listener factory binds
        to ``0.0.0.0:8080`` rather than refusing to construct.
        """
        from chumicro_http_server._wire import (
            DEFAULT_MAX_CONNECTIONS,
            DEFAULT_MAX_REQUEST_BODY_BYTES,
            DEFAULT_REQUEST_TIMEOUT_MS,
        )

        server = HttpServer.from_config(
            {}, listener_factory=lambda: _FakeListener([]),
        )
        assert server._max_connections == DEFAULT_MAX_CONNECTIONS  # noqa: SLF001
        assert server._request_timeout_ms == DEFAULT_REQUEST_TIMEOUT_MS  # noqa: SLF001
        assert server._max_request_body_bytes == DEFAULT_MAX_REQUEST_BODY_BYTES  # noqa: SLF001

    def test_partial_config_mixes_overrides_with_defaults(self) -> None:
        """Caller-set keys win; absent keys take defaults."""
        from chumicro_http_server._wire import DEFAULT_REQUEST_TIMEOUT_MS

        server = HttpServer.from_config(
            {"http_server.max_connections": 16},
            listener_factory=lambda: _FakeListener([]),
        )
        assert server._max_connections == 16  # noqa: SLF001
        assert server._request_timeout_ms == DEFAULT_REQUEST_TIMEOUT_MS  # noqa: SLF001

    def test_handler_kwarg_passes_through(self) -> None:
        """``handler=`` reaches the constructor as the fallback handler."""
        my_handler = lambda request: build_response(200, text="hi")  # noqa: E731
        server = HttpServer.from_config(
            {}, handler=my_handler,
            listener_factory=lambda: _FakeListener([]),
        )
        assert server._fallback_handler is my_handler  # noqa: SLF001

    def test_runtime_config_wrapper_works_too(self) -> None:
        """Real ``RuntimeConfig`` instance — same flat-key reads as a dict."""
        from chumicro_config import RuntimeConfig

        config = RuntimeConfig({"http_server.max_connections": 12})
        server = HttpServer.from_config(
            config, listener_factory=lambda: _FakeListener([]),
        )
        assert server._max_connections == 12  # noqa: SLF001

    def test_explicit_listener_factory_bypasses_auto_build(self) -> None:
        """Passing listener_factory= skips the chumicro_sockets path
        — caller owns the bind / TLS behaviour."""
        listener = _FakeListener([])
        custom_factory = lambda: listener  # noqa: E731
        server = HttpServer.from_config(
            {"http_server.bind_host": "ignored"},
            listener_factory=custom_factory,
        )
        assert server._listener_factory is custom_factory  # noqa: SLF001

    def test_default_factory_routes_plain_tcp_when_no_tls_config(self) -> None:
        """Empty config → factory calls ``tcp_listening_socket`` with
        the library defaults (``0.0.0.0:8080``)."""
        import chumicro_sockets as sockets_mod

        captured: dict = {}
        sentinel_listener = _FakeListener([])

        def fake_tcp(host, port, *, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["radio"] = radio
            return sentinel_listener

        original = sockets_mod.tcp_listening_socket
        sockets_mod.tcp_listening_socket = fake_tcp
        try:
            server = HttpServer.from_config({}, radio="fake-radio")
            server._listener_factory()  # noqa: SLF001 — trigger lazy
        finally:
            sockets_mod.tcp_listening_socket = original

        assert captured["host"] == "0.0.0.0"
        assert captured["port"] == 8080
        assert captured["radio"] == "fake-radio"

    def test_default_factory_routes_tls_when_both_paths_set(self) -> None:
        """Both ``tls.cert_path`` + ``tls.key_path`` set → factory
        builds an SSLContext and routes through tls_listening_socket."""
        import chumicro_sockets as sockets_mod

        captured: dict = {}
        sentinel_context = object()
        sentinel_listener = _FakeListener([])

        def fake_ssl_paths(*, cert_path, key_path):
            captured["cert_path"] = cert_path
            captured["key_path"] = key_path
            return sentinel_context

        def fake_tls(host, port, *, context, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["context"] = context
            captured["radio"] = radio
            return sentinel_listener

        original_ssl = sockets_mod.ssl_context_with_cert_and_key_paths
        original_tls = sockets_mod.tls_listening_socket
        sockets_mod.ssl_context_with_cert_and_key_paths = fake_ssl_paths
        sockets_mod.tls_listening_socket = fake_tls
        try:
            server = HttpServer.from_config(
                {
                    "http_server.bind_port": 8443,
                    "http_server.tls.cert_path": "/etc/cert.pem",
                    "http_server.tls.key_path": "/etc/key.pem",
                },
            )
            server._listener_factory()  # noqa: SLF001 — trigger lazy
        finally:
            sockets_mod.ssl_context_with_cert_and_key_paths = original_ssl
            sockets_mod.tls_listening_socket = original_tls

        assert captured["cert_path"] == "/etc/cert.pem"
        assert captured["key_path"] == "/etc/key.pem"
        assert captured["context"] is sentinel_context
        assert captured["host"] == "0.0.0.0"
        assert captured["port"] == 8443

    def test_default_factory_routes_tls_when_explicit_ssl_context(self) -> None:
        """An explicit ``ssl_context=`` arg forces TLS without needing
        cert/key paths in config — the caller built the context already."""
        import chumicro_sockets as sockets_mod

        captured: dict = {}
        sentinel_context = object()

        def fake_tls(host, port, *, context, radio=None):
            captured["context"] = context
            return _FakeListener([])

        original_tls = sockets_mod.tls_listening_socket
        sockets_mod.tls_listening_socket = fake_tls
        try:
            server = HttpServer.from_config({}, ssl_context=sentinel_context)
            server._listener_factory()  # noqa: SLF001
        finally:
            sockets_mod.tls_listening_socket = original_tls

        assert captured["context"] is sentinel_context

    def test_half_tls_config_raises_missing_config_key(self) -> None:
        """``cert_path`` set but ``key_path`` missing (or vice versa)
        → ``MissingConfigKey``.  Both-or-neither is the only valid
        TLS config shape."""
        from chumicro_config import MissingConfigKey

        with raises(MissingConfigKey):
            HttpServer.from_config(
                {"http_server.tls.cert_path": "/etc/cert.pem"},
            )
        with raises(MissingConfigKey):
            HttpServer.from_config(
                {"http_server.tls.key_path": "/etc/key.pem"},
            )

    def test_does_not_raise_on_empty_config(self) -> None:
        """Documents the asymmetry vs ``MQTTClient.from_config``:
        empty config + no listener_factory override is valid input.
        Unlike mqtt, no MissingConfigKey is ever raised when nothing
        is configured (both-or-neither TLS is the only loud check)."""
        import chumicro_sockets as sockets_mod

        original = sockets_mod.tcp_listening_socket
        sockets_mod.tcp_listening_socket = (
            lambda host, port, *, radio=None: _FakeListener([])
        )
        try:
            server = HttpServer.from_config({})
        finally:
            sockets_mod.tcp_listening_socket = original
        assert server._max_connections > 0  # noqa: SLF001 — sanity

    def test_skipped_factory_module_raises_runtime_error(self) -> None:
        """When ``chumicro_http_server.sockets_factory`` is excluded
        via ``__chumicro_skip_factories__``, the default branch of
        ``from_config`` raises ``RuntimeError`` naming the bypass
        kwarg instead of leaking ``ImportError``.  CPython-only —
        sys.modules None-sentinel is CPython-specific; the
        translation behavior itself is runtime-agnostic.
        """
        import sys  # noqa: PLC0415

        from chumicro_test_harness import skip  # noqa: PLC0415

        if sys.implementation.name != "cpython":
            skip("sys.modules None-sentinel is CPython-specific")

        original = sys.modules.get("chumicro_http_server.sockets_factory")
        sys.modules["chumicro_http_server.sockets_factory"] = None
        try:
            try:
                HttpServer.from_config({})
            except RuntimeError as exception:
                assert "listener_factory=" in str(exception)
                assert "__chumicro_skip_factories__" in str(exception)
            else:
                raise AssertionError("expected RuntimeError")
        finally:
            if original is None:
                sys.modules.pop("chumicro_http_server.sockets_factory", None)
            else:
                sys.modules["chumicro_http_server.sockets_factory"] = original
