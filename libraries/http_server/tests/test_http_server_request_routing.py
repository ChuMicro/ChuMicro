"""http_server: in-flight observation, caller headers, Request
object, routing."""

from chumicro_http_server import (
    CaseInsensitiveDict,
    HttpServer,
    build_response,
    encode_response,
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

    def listener_factory():
        listener_called["count"] += 1
        return FakeListener(sockets)

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

def _connection(request_bytes):
    """Build a (FakeSocket, peer) tuple from a raw request byte-string."""
    socket = FakeSocket()
    socket.enqueue_recv(request_bytes)
    return socket, ("127.0.0.1", 12345)


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
        from chumicro_http_server import Response
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
        from chumicro_http_server import Request
        request = Request(
            method="POST", target="/", http_version="HTTP/1.1",
            headers=CaseInsensitiveDict(),
            body="café".encode(),
            peer=("127.0.0.1", 1),
        )
        assert request.text() == "café"

    def test_json_decodes(self):
        from chumicro_http_server import Request
        request = Request(
            method="POST", target="/", http_version="HTTP/1.1",
            headers=CaseInsensitiveDict(),
            body=b'{"k": "v"}',
            peer=("127.0.0.1", 1),
        )
        assert request.json() == {"k": "v"}

    def test_repr_includes_method_target_peer(self):
        from chumicro_http_server import Request
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
        from chumicro_http_server import Response
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
            listener_factory=lambda: FakeListener(sockets),
            ticks=ticks,
            **kwargs,
        )
        return server, ticks

    def test_route_decorator_registers_handler(self):
        sock, peer = _connection(request_bytes(method="GET", path="/api"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/api")
        def index(request):
            return build_response(200, text=f"hello-{request.method}")

        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 200 OK\r\n")
        assert sock.sent.endswith(b"\r\n\r\nhello-GET")

    def test_route_default_method_is_get(self):
        sock_get, peer_get = _connection(request_bytes(method="GET", path="/x"))
        sock_post, peer_post = _connection(request_bytes(method="POST", path="/x"))
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
        sock_get, peer_get = _connection(request_bytes(method="GET", path="/api"))
        sock_post, peer_post = _connection(request_bytes(method="POST", path="/api"))
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
        sock, peer = _connection(request_bytes(method="GET", path="/widgets/42"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/widgets/<id>")
        def widget(request):
            return build_response(200, text=f"id={request.path_params['id']}")

        _drive_until_idle(server, ticks)
        assert sock.sent.endswith(b"\r\n\r\nid=42")

    def test_path_param_with_query_string(self):
        sock, peer = _connection(
            request_bytes(method="GET", path="/widgets/abc?fields=name"),
        )
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/widgets/<id>")
        def widget(request):
            assert request.query["fields"] == "name"
            return build_response(200, text=request.path_params["id"])

        _drive_until_idle(server, ticks)
        assert sock.sent.endswith(b"\r\n\r\nabc")

    def test_unrouted_path_returns_404(self):
        sock, peer = _connection(request_bytes(method="GET", path="/nope"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/api")
        def api(_request):
            return build_response(200)

        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 404 Not Found\r\n")

    def test_method_not_allowed_returns_405_with_allow_header(self):
        sock, peer = _connection(request_bytes(method="DELETE", path="/api"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/api", methods=["GET", "POST"])
        def api(_request):
            return build_response(200)

        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 405 Method Not Allowed\r\n")
        # Allow header lists both registered methods (sorted).
        assert b"Allow: GET, POST\r\n" in sock.sent

    def test_method_not_allowed_for_pattern_route(self):
        sock, peer = _connection(request_bytes(method="DELETE", path="/widgets/42"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/widgets/<id>", methods=["GET"])
        def widget(_request):
            return build_response(200)

        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 405 Method Not Allowed\r\n")
        assert b"Allow: GET\r\n" in sock.sent

    def test_fallback_handler_used_when_no_route_matches(self):
        sock, peer = _connection(request_bytes(method="GET", path="/anywhere"))
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
        sock, peer = _connection(request_bytes(method="GET", path="/api"))
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
        sock, peer = _connection(request_bytes())
        server, ticks = self._route_server([(sock, peer)])
        # No @route, no fallback handler.
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 404 Not Found\r\n")

    def test_re_register_overrides_previous_handler(self):
        sock, peer = _connection(request_bytes(method="GET", path="/x"))
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
        sock, peer = _connection(request_bytes(method="GET", path="/items/x"))
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
        sock, peer = _connection(request_bytes(method="POST", path="/api"))
        server, ticks = self._route_server([(sock, peer)])

        @server.route("/api", methods=["post"])  # lowercase
        def api(_request):
            return build_response(201, text="ok")

        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 201 Created\r\n")
