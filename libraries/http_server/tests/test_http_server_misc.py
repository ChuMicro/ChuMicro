"""http_server: respond method, accept variants, body state
transition, charset parsing."""

import select

from chumicro_http_server import (
    HttpServer,
    Response,
    build_response,
    parse_charset,
)
from chumicro_http_server.testing import FakeListener
from chumicro_runner import IO_READ, IO_WRITE, Runner
from chumicro_runner.testing import FakePoller
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
            transport_factory=lambda: NoneListener(),
            handler=lambda request: build_response(200),
            ticks=ticks,
        )
        server.handle(ticks.ticks_ms())
        assert server.in_flight == 0
        assert server.listening is True


class TestAuditFixes:
    def test_unencodable_response_becomes_500_not_crash(self):
        # A handler that returns a Response with a str body makes
        # encode_response raise; it must be turned into a 500, not escape
        # tick()/handle() and re-run the handler forever.
        sock = FakeSocket()
        sock.enqueue_recv(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        invocations = []

        def bad_handler(request):
            invocations.append(1)
            return Response(
                status_code=200, reason="OK", headers={}, body="not-bytes",
            )

        server, ticks, _ = _make_server(
            sockets=[(sock, ("peer", 1))], handler=bad_handler,
        )
        for _ in range(12):
            server.handle(ticks.ticks_ms())  # must never raise
            ticks.advance(1)
        assert len(invocations) == 1  # handler ran once, not in a crash loop
        assert b"500" in bytes(sock.sent)

    def test_non_eagain_accept_error_is_scoped_not_fatal(self):
        # A TLS handshake failure surfaces as a non-EAGAIN OSError from
        # accept(); it must be recorded, not tear down the server loop.
        class BadAcceptListener:
            def accept(self):
                raise OSError(1, "TLS handshake failed")

            def close(self):
                pass

            def setblocking(self, _flag):
                pass

        ticks = FakeTicks()
        server = HttpServer(
            transport_factory=lambda: BadAcceptListener(),
            handler=lambda request: build_response(200),
            ticks=ticks,
        )
        server.handle(ticks.ticks_ms())  # must not raise
        server.handle(ticks.ticks_ms())
        assert server.listening is True
        assert server.accept_errors == 2

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
            transport_factory=lambda: FakeListener([(sock, ("127.0.0.1", 1))]),
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


class TestRunnerReactorContract:
    """``io_socket`` / ``io_interest`` / ``next_deadline`` let
    ``Runner.wait`` register the listener socket and idle the loop until
    accept readiness or the earliest in-flight connection deadline.
    In-flight per-connection I/O is driven on the periodic ``handle()``
    tick, not via per-socket poll registration."""

    def test_io_socket_none_before_first_tick(self):
        """Listener is lazy-opened in handle()."""
        server, _ticks, _ = _make_server(sockets=[])
        assert server.io_socket is None

    def test_io_socket_returns_listener_after_first_tick(self):
        server, ticks, _ = _make_server(sockets=[])
        server.handle(ticks.ticks_ms())
        # FakeListener exposes no ``.sock``, so the property returns it
        # directly; production listener wrappers expose ``.sock`` and the
        # property unwraps to that pollable OS-level socket.
        assert server.io_socket is server._listener

    def test_io_interest_read_after_listener_open(self):
        server, ticks, _ = _make_server(sockets=[])
        assert server.io_interest(ticks.ticks_ms()) == 0  # listener still None
        server.handle(ticks.ticks_ms())
        assert server.io_interest(ticks.ticks_ms()) == IO_READ

    def test_io_interest_never_wants_write(self):
        """The listener is not a write target."""
        server, ticks, _ = _make_server(sockets=[])
        server.handle(ticks.ticks_ms())
        assert server.io_interest(ticks.ticks_ms()) & IO_WRITE == 0

    def test_next_deadline_none_with_no_in_flight_connections(self):
        server, ticks, _ = _make_server(sockets=[])
        server.handle(ticks.ticks_ms())
        assert server.next_deadline(ticks.ticks_ms()) is None

    def test_next_deadline_returns_earliest_connection_deadline(self):
        """Accept a connection, observe next_deadline capped at the
        short progress interval while a connection is in flight.

        The connection's socket isn't in the runner's poll set (only the
        listener is), so next_deadline must return a near-term wake — not
        the far request-timeout deadline — or Runner.wait would sleep
        while the connection's bytes sit unread."""
        peer = FakeSocket()
        # Stall the recv so the connection stays mid-request without
        # being treated as a peer close.  Without this the empty queue
        # returns 0 bytes and the connection finalizes on first tick.
        peer.enqueue_eagain_for_recv(99)
        server, ticks, _ = _make_server(
            sockets=[(peer, ("peer", 1234))],
            request_timeout_ms=1500,
        )
        accept_tick = ticks.ticks_ms()
        server.handle(accept_tick)  # lazy-open listener + accept
        assert server.in_flight == 1

        deadline = server.next_deadline(ticks.ticks_ms())
        assert deadline is not None
        # Progress interval (20 ms) wins over the far 1500 ms deadline.
        assert ticks.ticks_diff(deadline, accept_tick) == 20

    def test_runner_wait_registers_listener_for_accept_readiness(self):
        """End-to-end: drop HttpServer into a Runner with a FakePoller
        and observe the listener registered for POLLIN once handle()
        lazy-opens it."""
        ticks = FakeTicks()
        poller = FakePoller()
        runner = Runner(ticks=ticks, poller=poller)
        server, _, _ = _make_server(sockets=[])
        # Override the server's ticks with the runner's so they share clock.
        server._ticks = ticks
        runner.add(server)

        # First wait: listener still None, no socket registered.
        runner.wait(ticks.ticks_ms())
        assert poller.register_calls == []

        # tick() runs handle() -> opens the listener.  wait() then
        # registers it for POLLIN.
        runner.tick()
        runner.wait(ticks.ticks_ms())

        assert any(
            eventmask == select.POLLIN
            for _sock, eventmask in poller.register_calls
        )
