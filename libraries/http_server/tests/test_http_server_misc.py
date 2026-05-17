"""http_server: respond method, accept variants, body state
transition, charset parsing."""

from chumicro_http_server import (
    HttpServer,
    build_response,
    parse_charset,
)
from chumicro_http_server.testing import FakeListener
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
            listener_factory=lambda: FakeListener([(sock, ("127.0.0.1", 1))]),
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
