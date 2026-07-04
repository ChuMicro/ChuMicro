"""WebSocket server tests (chumicro_websockets.server): constructor,
accept, handshake, handshake rejection."""

from chumicro_runner import IO_READ, IO_WRITE
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    WebSocketServer,
    WebSocketState,
    derive_accept_key,
    make_websocket_key,
)
from chumicro_websockets._wire import (
    HandshakeResponseParser,
    encode_client_handshake,
)
from chumicro_websockets.server import ServerHandshakePhase
from chumicro_websockets.testing import (
    FakeConnection,
    FakeListener,
)

FakeSocket = FakeConnection

def _noop_connection(_conn):
    """Default ``on_connection`` for tests that don't care about callbacks."""

def _make_server(*, on_connection=None, **kwargs):
    listener = FakeListener()
    clock = FakeTicks()
    if on_connection is None:
        on_connection = _noop_connection
    server = WebSocketServer(
        listener=listener,
        on_connection=on_connection,
        ticks=clock,
        **kwargs,
    )
    return server, listener, clock

def _client_handshake_bytes(path="/", host="example.com", *, key=None) -> bytes:
    """Build a well-formed client upgrade GET to feed at the server."""
    if key is None:
        key = make_websocket_key()
    return encode_client_handshake(host, 80, path, key)

def _drive_server_handshake(
    server: WebSocketServer,
    listener: FakeListener,
    clock: FakeTicks,
    *,
    path: str = "/",
) -> tuple[FakeSocket, str, bytes]:
    """Queue an accepted socket, feed a client handshake, drive to OPEN.

    Returns ``(peer_socket, client_key, server_response_bytes)``.
    """
    peer = FakeSocket()
    listener.queue_accept(peer)
    key = make_websocket_key()
    request = _client_handshake_bytes(path=path, key=key)
    peer.feed_inbound(request)
    # Tick: accept + read request + reach SENDING_RESPONSE.
    server.handle(clock.ticks_ms())
    # Tick: send the 101 response, transition to OPEN.
    while True:
        connection = server.connections[0]
        if connection.state == WebSocketState.OPEN:
            break
        if connection.state == WebSocketState.CLOSED:
            break
        server.handle(clock.ticks_ms())
    response = peer.read_outbound()
    return peer, key, response


class TestServerConstructor:
    def test_initial_state(self):
        server, _listener, _clock = _make_server()
        assert server.connection_count == 0
        assert server.connections == ()
        assert server.closed is False

    def test_check_returns_true_when_idle(self):
        server, _listener, clock = _make_server()
        # Conservative: always True until close().
        assert server.check(clock.ticks_ms()) is True

    def test_check_after_close_returns_false(self):
        server, _listener, clock = _make_server()
        server.close()
        assert server.check(clock.ticks_ms()) is False

    def test_handle_after_close_is_noop(self):
        server, listener, clock = _make_server()
        server.close()
        peer = FakeSocket()
        listener.queue_accept(peer)
        server.handle(clock.ticks_ms())
        assert server.connection_count == 0


class TestAccept:
    def test_no_pending_connection_keeps_count_zero(self):
        server, _listener, clock = _make_server()
        server.handle(clock.ticks_ms())
        assert server.connection_count == 0

    def test_pending_connection_creates_connection_object(self):
        server, listener, clock = _make_server()
        peer = FakeSocket()
        listener.queue_accept(peer)
        server.handle(clock.ticks_ms())
        assert server.connection_count == 1

    def test_max_connections_limit_respected(self):
        server, listener, clock = _make_server(max_connections=2)
        for _index in range(5):
            listener.queue_accept(FakeSocket())
        server.handle(clock.ticks_ms())
        assert server.connection_count == 2

    def test_listener_error_does_not_raise(self):
        server, listener, clock = _make_server()
        original_accept = listener.accept

        def _raise(*_args, **_kwargs):
            raise OSError(99, "listener dead")

        listener.accept = _raise
        server.handle(clock.ticks_ms())
        assert server.connection_count == 0
        listener.accept = original_accept

    def test_listener_error_recorded_on_last_error(self):
        server, listener, clock = _make_server()
        assert server.last_error is None
        boom = OSError(99, "listener dead")

        def _raise(*_args, **_kwargs):
            raise boom

        listener.accept = _raise
        server.handle(clock.ticks_ms())
        assert server.last_error is boom

    def test_eagain_does_not_set_last_error(self):
        server, _listener, clock = _make_server()
        # No queued accepts → FakeListener.accept raises OSError(EAGAIN).
        server.handle(clock.ticks_ms())
        assert server.last_error is None


class TestHandshake:
    def test_full_handshake_reaches_open(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda conn: observed.append(conn),
        )
        peer, key, response = _drive_server_handshake(server, listener, clock)
        assert observed
        connection = observed[0]
        assert connection.state == WebSocketState.OPEN
        # Validate the response derives the right accept token.
        parser = HandshakeResponseParser(derive_accept_key(key))
        parser.feed(response)
        assert parser.status_code == 101

    def test_request_path_recorded(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda conn: observed.append(conn),
        )
        _drive_server_handshake(server, listener, clock, path="/chat")
        assert observed[0].request_path == "/chat"

    def test_request_headers_recorded(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda conn: observed.append(conn),
        )
        _drive_server_handshake(server, listener, clock)
        headers = observed[0].request_headers
        assert headers["Upgrade"] == "websocket"
        assert "Sec-WebSocket-Key" in headers


class TestHandshakeRejection:
    def test_malformed_request_returns_400(self):
        server, listener, clock = _make_server()
        peer = FakeSocket()
        listener.queue_accept(peer)
        peer.feed_inbound(b"POST / HTTP/1.1\r\n\r\n")
        server.handle(clock.ticks_ms())
        # Inspect the bytes the server pushed back.
        response = peer.read_outbound()
        assert response.startswith(b"HTTP/1.1 400 Bad Request\r\n")
        assert peer.closed is True

    def test_accept_path_filter_rejects_other_paths(self):
        server, listener, clock = _make_server(accept_path="/ws")
        peer, _key, _response = (
            FakeSocket(),
            None,
            None,
        )
        listener.queue_accept(peer)
        request = _client_handshake_bytes(path="/other")
        peer.feed_inbound(request)
        server.handle(clock.ticks_ms())
        response = peer.read_outbound()
        assert response.startswith(b"HTTP/1.1 404 Not Found\r\n")
        assert peer.closed is True

    def test_accept_path_filter_accepts_match(self):
        observed = []
        server, listener, clock = _make_server(
            accept_path="/ws",
            on_connection=lambda conn: observed.append(conn),
        )
        _drive_server_handshake(server, listener, clock, path="/ws")
        assert observed
        assert observed[0].request_path == "/ws"

    def test_handshake_timeout(self):
        server, listener, clock = _make_server(handshake_timeout_ms=1000)
        peer = FakeSocket()
        listener.queue_accept(peer)
        # Send a partial request that never completes.
        peer.feed_inbound(b"GET / HTTP/1.1\r\nHost: x\r\n")
        server.handle(clock.ticks_ms())
        clock.advance(1500)
        server.handle(clock.ticks_ms())
        # Connection finalized.  Removed from the active list.
        assert server.connection_count == 0
        assert peer.closed is True

    def test_client_eof_mid_handshake(self):
        server, listener, clock = _make_server()
        peer = FakeSocket()
        listener.queue_accept(peer)
        peer.close_inbound()
        server.handle(clock.ticks_ms())
        assert server.connection_count == 0

    def test_on_connection_raise_kills_connection(self):
        def boom(_conn):
            raise RuntimeError("user policy rejected")

        server, listener, clock = _make_server(on_connection=boom)
        peer = FakeSocket()
        listener.queue_accept(peer)
        peer.feed_inbound(_client_handshake_bytes())
        server.handle(clock.ticks_ms())
        # Drive sending the 101 + entering OPEN (which fires callback that raises).
        for _tick in range(5):
            if server.connection_count == 0:
                break
            server.handle(clock.ticks_ms())
        assert server.connection_count == 0
        assert peer.closed is True


class TestServerRunnerReactorContract:
    """Server ``Connection`` exposes ``io_*`` / ``next_deadline`` mirroring
    the client but with the handshake legs reversed (server reads the
    upgrade request, then writes the 101 response)."""

    def _accepted_connection(self):
        """Accept a peer and return the connection paused in READING_REQUEST."""
        server, listener, clock = _make_server()
        peer = FakeSocket()
        listener.queue_accept(peer)
        # One handle() tick accepts and creates the connection but does
        # not yet feed any handshake bytes (peer.inbound is empty).
        server.handle(clock.ticks_ms())
        return server, peer, clock

    def test_io_socket_returns_peer_socket_while_handshake_phase(self):
        server, peer, _clock = self._accepted_connection()
        connection = server.connections[0]
        assert connection.io_socket is peer

    def test_io_interest_read_during_reading_request(self):
        server, _peer, _clock = self._accepted_connection()
        connection = server.connections[0]
        assert connection._handshake_phase == ServerHandshakePhase.READING_REQUEST
        assert connection.io_interest(0) == IO_READ

    def test_io_interest_write_during_sending_response(self):
        server, peer, clock = self._accepted_connection()
        # Feed the client's upgrade so the connection advances to
        # SENDING_RESPONSE on the next tick.
        peer.feed_inbound(_client_handshake_bytes())
        server.handle(clock.ticks_ms())
        connection = server.connections[0]
        assert connection._handshake_phase == ServerHandshakePhase.SENDING_RESPONSE
        assert connection.io_interest(0) == IO_WRITE

    def test_io_interest_read_when_open(self):
        server, listener, clock = _make_server()
        _drive_server_handshake(server, listener, clock)
        connection = server.connections[0]
        assert connection.state == WebSocketState.OPEN
        assert connection.io_interest(0) == IO_READ

    def test_next_deadline_returns_handshake_deadline_during_handshake(self):
        server, peer, clock = self._accepted_connection()
        connection = server.connections[0]
        deadline = connection.next_deadline(clock.ticks_ms())
        assert deadline is not None
        # The handshake deadline is set at accept time to *now + timeout*.
        assert clock.ticks_diff(deadline, clock.ticks_ms()) > 0

    def test_next_deadline_none_when_open_and_idle(self):
        server, listener, clock = _make_server()
        _drive_server_handshake(server, listener, clock)
        connection = server.connections[0]
        assert connection.next_deadline(clock.ticks_ms()) is None
