"""Tests for chumicro_http_server slice 7a — listener + parser + canned response.

Decision 0041: HttpServer is runner-shaped (check / handle), each
connection is a state machine advanced one chunk per tick, single
caller-provided handler in 7a (routing lands in 7b).

These tests use a fake listener that hands out :class:`FakeSocket`
pre-loaded with the request bytes — the server thinks it accepted a
real connection, parses the request, runs the handler, writes the
response back to the FakeSocket's `sent` buffer where tests assert.
"""

import pytest
from chumicro_http_server import (
    HttpServer,
    RequestParser,
    RequestParseState,
    ServerProtocolError,
    build_response,
    encode_response,
    parse_query,
    split_target,
)
from chumicro_sockets.testing import FakeSocket
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
        ticks_ms_func=ticks.ticks_ms,
        ticks_add_func=ticks.ticks_add,
        ticks_diff_func=ticks.ticks_diff,
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
        with pytest.raises(ValueError, match="at most one"):
            build_response(200, body=b"x", json={"k": "v"})

    def test_non_bytes_str_body_rejected(self):
        with pytest.raises(TypeError, match="bytes / bytearray / str"):
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
            "recv_into": lambda self, _b, _n=0: (_ for _ in ()).throw(OSError(11)),
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
            ticks_ms_func=ticks.ticks_ms,
            ticks_add_func=ticks.ticks_add,
            ticks_diff_func=ticks.ticks_diff,
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
            ticks_ms_func=ticks.ticks_ms,
            ticks_add_func=ticks.ticks_add,
            ticks_diff_func=ticks.ticks_diff,
        )
        # Drive a few ticks; connection should be stalled mid-body, not done.
        for _ in range(5):
            server.handle(ticks.ticks_ms())
            ticks.advance(1)
        assert server.in_flight == 1
        # Cleanup
        server.close()
