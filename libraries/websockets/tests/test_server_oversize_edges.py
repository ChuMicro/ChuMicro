"""WebSocket server tests (chumicro_websockets.server): oversize,
frame-level oversize, server close, connection edges."""

from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    OPCODE_CONTINUATION,
    OPCODE_TEXT,
    WebSocketServer,
    WebSocketState,
    WebSocketTimeoutError,
    WhenOversized,
    make_websocket_key,
)
from chumicro_websockets._wire import (
    encode_client_handshake,
    encode_frame,
    make_mask_key,
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


class TestOversize:
    def test_drop_with_event_fires_and_stays_open(self):
        observed = []
        oversized = []

        def on_open(conn):
            conn.on_oversized = lambda reported_length: oversized.append(reported_length)

        server, listener, clock = _make_server(
            max_message_bytes=10,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
            on_connection=lambda connection: (observed.append(connection), on_open(connection)),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(
            encode_frame(OPCODE_TEXT, b"01234", fin=False, mask=make_mask_key())
            + encode_frame(OPCODE_CONTINUATION, b"5678901234", fin=True, mask=make_mask_key()),
        )
        server.handle(clock.ticks_ms())
        server.handle(clock.ticks_ms())
        assert oversized
        # Connection still OPEN; ready for next inbound message.
        assert observed[0].state == WebSocketState.OPEN

    def test_drop_with_event_next_message_arrives_intact(self):
        """After an oversized assembly is dropped, the framing stream
        stays aligned and the very next client→server message reaches
        ``on_text``.
        """
        observed = []
        oversized = []
        received = []

        def on_open(conn):
            conn.on_text = lambda text: received.append(text)
            conn.on_oversized = lambda reported_length: oversized.append(reported_length)

        server, listener, clock = _make_server(
            max_message_bytes=10,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
            on_connection=lambda connection: (observed.append(connection), on_open(connection)),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(
            encode_frame(OPCODE_TEXT, b"AAAAA", fin=False, mask=make_mask_key())
            + encode_frame(OPCODE_CONTINUATION, b"BBBBB", fin=False, mask=make_mask_key())
            + encode_frame(OPCODE_CONTINUATION, b"CCCCC", fin=True, mask=make_mask_key())
            + encode_frame(OPCODE_TEXT, b"hello", fin=True, mask=make_mask_key()),
        )
        for _index in range(6):
            server.handle(clock.ticks_ms())
        assert oversized, "on_oversized never fired"
        assert observed[0].state == WebSocketState.OPEN, (
            f"expected OPEN, got {observed[0].state}"
        )
        assert received == ["hello"], (
            f"next message lost or corrupted; got {received!r}"
        )

    def test_drop_silent(self):
        oversized = []

        def on_open(conn):
            conn.on_oversized = lambda reported_length: oversized.append(reported_length)

        server, listener, clock = _make_server(
            max_message_bytes=10,
            when_oversized=WhenOversized.DROP_SILENT,
            on_connection=on_open,
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(
            encode_frame(OPCODE_TEXT, b"01234", fin=False, mask=make_mask_key())
            + encode_frame(OPCODE_CONTINUATION, b"5678901234", fin=True, mask=make_mask_key()),
        )
        server.handle(clock.ticks_ms())
        server.handle(clock.ticks_ms())
        assert oversized == []
        # Connection still OPEN.
        assert server.connections[0].state == WebSocketState.OPEN

    def test_disconnect(self):
        oversized = []
        observed = []

        def on_open(connection):
            observed.append(connection)
            connection.on_oversized = lambda reported_length: oversized.append(reported_length)

        server, listener, clock = _make_server(
            max_message_bytes=10,
            when_oversized=WhenOversized.DISCONNECT,
            on_connection=on_open,
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(
            encode_frame(OPCODE_TEXT, b"01234", fin=False, mask=make_mask_key())
            + encode_frame(OPCODE_CONTINUATION, b"5678901234", fin=True, mask=make_mask_key()),
        )
        server.handle(clock.ticks_ms())
        server.handle(clock.ticks_ms())
        assert oversized == []  # DISCONNECT does NOT fire on_oversized
        # Connection transitioned to CLOSING; peer echoes close to finalize.
        assert observed[0].state in (WebSocketState.CLOSING, WebSocketState.CLOSED)


class TestFrameLevelOversize:
    """A single inbound client frame > the cap used to terminate the
    connection with ``CLOSE_PROTOCOL_ERROR``; now it drains at the
    frame layer (tier 3 in :class:`FrameParser`) and the server
    applies its ``WhenOversized`` policy.  Matches the shared
    cross-library oversize contract — ``DROP_WITH_EVENT`` drops the
    payload and stays connected, like ``chumicro-mqtt`` and
    ``chumicro-requests``.
    """

    def test_drop_with_event_reports_frame_length(self):
        oversized = []
        observed = []

        def on_open(connection):
            observed.append(connection)
            connection.on_oversized = lambda reported_length: oversized.append(reported_length)

        server, listener, clock = _make_server(
            max_message_bytes=100,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
            on_connection=on_open,
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(
            encode_frame(OPCODE_TEXT, b"X" * 500, fin=True, mask=make_mask_key()),
        )
        for _index in range(6):
            server.handle(clock.ticks_ms())
        assert oversized == [500]
        assert observed[0].state == WebSocketState.OPEN

    def test_normal_message_after_oversize_drain(self):
        received = []
        oversized = []
        observed = []

        def on_open(connection):
            observed.append(connection)
            connection.on_text = lambda text: received.append(text)
            connection.on_oversized = lambda reported_length: oversized.append(reported_length)

        server, listener, clock = _make_server(
            max_message_bytes=100,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
            on_connection=on_open,
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(
            encode_frame(OPCODE_TEXT, b"X" * 500, fin=True, mask=make_mask_key())
            + encode_frame(OPCODE_TEXT, b"hello", fin=True, mask=make_mask_key()),
        )
        for _index in range(8):
            server.handle(clock.ticks_ms())
        assert oversized == [500]
        assert received == ["hello"]
        assert observed[0].state == WebSocketState.OPEN


class TestServerClose:
    def test_close_drains_listener_and_connections(self):
        observed = []
        closes = []

        def on_open(connection):
            observed.append(connection)
            connection.on_close = lambda code, reason: closes.append((code, reason))

        server, listener, clock = _make_server(on_connection=on_open)
        _drive_server_handshake(server, listener, clock)
        server.close()
        assert server.closed is True
        assert listener.closed is True
        assert closes  # on_close fired during teardown
        assert observed[0].state == WebSocketState.CLOSED

    def test_close_idempotent(self):
        server, _listener, _clock = _make_server()
        server.close()
        server.close()  # must not raise
        assert server.closed is True


class TestConnectionEdges:
    def test_handshake_send_eagain_keeps_state(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer = FakeSocket()
        listener.queue_accept(peer)
        peer.feed_inbound(_client_handshake_bytes())
        server.handle(clock.ticks_ms())  # accepts + reads request + transitions to SENDING_RESPONSE
        peer.raise_on_send = OSError(11, "would block")
        server.handle(clock.ticks_ms())  # send EAGAIN — state unchanged
        connection = server.connections[0]
        assert connection.state == WebSocketState.CONNECTING
        assert connection._handshake_phase == ServerHandshakePhase.SENDING_RESPONSE

    def test_handshake_send_error_finalizes(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer = FakeSocket()
        listener.queue_accept(peer)
        peer.feed_inbound(_client_handshake_bytes())
        server.handle(clock.ticks_ms())
        peer.raise_on_send = OSError(99, "send dead")
        server.handle(clock.ticks_ms())
        # Server removes the dead connection on the same tick as the failure.
        assert server.connection_count == 0
        assert observed == []  # never reached OPEN, so on_connection was never called
        assert peer.closed is True

    def test_recv_error_in_open_finalizes(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.raise_on_recv = OSError(99, "recv dead")
        server.handle(clock.ticks_ms())
        assert observed[0].state == WebSocketState.CLOSED

    def test_send_error_in_open_finalizes(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        observed[0].send_text("hello")
        peer.raise_on_send = OSError(99, "send dead")
        server.handle(clock.ticks_ms())
        assert observed[0].state == WebSocketState.CLOSED

    def test_send_ping_oversize_payload_raises(self):
        from chumicro_websockets import WebSocketProtocolError
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        _drive_server_handshake(server, listener, clock)
        with raises(WebSocketProtocolError, match="125"):
            observed[0].send_ping(b"X" * 200)

    def test_connection_check_returns_false_when_closed(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        _drive_server_handshake(server, listener, clock)
        observed[0].state = WebSocketState.CLOSED
        assert observed[0].check(clock.ticks_ms()) is False

    def test_pong_overdue_finalizes(self):
        observed = []
        server, listener, clock = _make_server(
            pong_timeout_ms=1000,
            on_connection=lambda connection: observed.append(connection),
        )
        _drive_server_handshake(server, listener, clock)
        observed[0].send_ping(b"hb")
        server.handle(clock.ticks_ms())
        clock.advance(1500)
        server.handle(clock.ticks_ms())
        assert observed[0].state == WebSocketState.CLOSED
        assert isinstance(observed[0].last_error, WebSocketTimeoutError)

    def test_partial_handshake_send_resumes(self):
        observed = []
        # Tiny send budget forces multi-tick handshake response transmission.
        server, listener, clock = _make_server(
            send_budget_per_tick=4,
            on_connection=lambda connection: observed.append(connection),
        )
        peer = FakeSocket()
        listener.queue_accept(peer)
        peer.feed_inbound(_client_handshake_bytes())
        for _tick in range(60):
            server.handle(clock.ticks_ms())
            if server.connections and server.connections[0].state == WebSocketState.OPEN:
                break
        assert observed
        assert observed[0].state == WebSocketState.OPEN

    def test_handshake_send_returns_zero_keeps_state(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer = FakeSocket()
        listener.queue_accept(peer)
        peer.feed_inbound(_client_handshake_bytes())
        server.handle(clock.ticks_ms())  # reach SENDING_RESPONSE
        # Patch send to return 0 transiently.
        original_send = peer.send
        peer.send = lambda _data: 0
        server.handle(clock.ticks_ms())
        connection = server.connections[0]
        assert connection.state == WebSocketState.CONNECTING
        peer.send = original_send
