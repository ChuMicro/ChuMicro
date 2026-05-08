"""Tests for chumicro_websockets.WebSocketServer + Connection — slice 3.

Drives the server against an in-memory ``FakeListener`` whose
``accept()`` hands out ``FakeSocket`` instances (the same shape the
client tests use, lifted to ``chumicro_websockets.testing`` in
slice 4).  Exercises:

* Accept loop + ``max_connections`` cap.
* Per-connection handshake (request parse → 101 send → OPEN).
* ``accept_path`` filter (404 on mismatch).
* Inbound mask validation (client must mask).
* Outbound is unmasked.
* All the OPEN/CLOSING/CLOSED dynamics: text/binary/ping/pong, close
  handshake, oversize, fragmentation, callbacks.
"""

import struct

from chumicro_test_harness.assertions import raises
from chumicro_websockets import (
    CLOSE_BAD_DATA,
    CLOSE_GOING_AWAY,
    CLOSE_PROTOCOL_ERROR,
    CLOSE_TOO_BIG,
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_CONTINUATION,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    Connection,
    WebSocketBackpressureError,
    WebSocketServer,
    WebSocketState,
    WebSocketStateError,
    WebSocketTimeoutError,
    WhenOversized,
    derive_accept_key,
    make_websocket_key,
)
from chumicro_websockets._wire import (
    FrameParser,
    HandshakeResponseParser,
    encode_client_handshake,
    encode_close_payload,
    encode_frame,
    make_mask_key,
)
from chumicro_websockets.server import ServerHandshakePhase
from chumicro_websockets.testing import FakeConnection, FakeListener, TickClock

# Backwards-compatible alias for in-test references.
FakeSocket = FakeConnection


def _noop_connection(_conn):
    """Default ``on_connection`` for tests that don't care about callbacks."""


def _make_server(*, on_connection=None, **kwargs):
    listener = FakeListener()
    clock = TickClock()
    if on_connection is None:
        on_connection = _noop_connection
    server = WebSocketServer(
        listener=listener,
        on_connection=on_connection,
        ticks_ms_func=clock.now,
        ticks_add_func=clock.add,
        ticks_diff_func=clock.diff,
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
    clock: TickClock,
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
    server.handle(clock.now())
    # Tick: send the 101 response, transition to OPEN.
    while True:
        connection = server.connections[0]
        if connection.state == WebSocketState.OPEN:
            break
        if connection.state == WebSocketState.CLOSED:
            break
        server.handle(clock.now())
    response = peer.read_outbound()
    return peer, key, response


def _server_frame(opcode: int, payload: bytes) -> bytes:
    """Encode a client→server frame (masked) for inbound feeding."""
    return encode_frame(opcode, payload, fin=True, mask=make_mask_key())


# ---------------------------------------------------------------------------
# Constructor + properties
# ---------------------------------------------------------------------------


class TestServerConstructor:
    def test_initial_state(self):
        server, _listener, _clock = _make_server()
        assert server.connection_count == 0
        assert server.connections == ()
        assert server.closed is False

    def test_check_returns_true_when_idle(self):
        server, _listener, clock = _make_server()
        # Conservative — always True until close().
        assert server.check(clock.now()) is True

    def test_check_after_close_returns_false(self):
        server, _listener, clock = _make_server()
        server.close()
        assert server.check(clock.now()) is False

    def test_handle_after_close_is_noop(self):
        server, listener, clock = _make_server()
        server.close()
        peer = FakeSocket()
        listener.queue_accept(peer)
        server.handle(clock.now())
        assert server.connection_count == 0


# ---------------------------------------------------------------------------
# Accept loop
# ---------------------------------------------------------------------------


class TestAccept:
    def test_no_pending_connection_keeps_count_zero(self):
        server, _listener, clock = _make_server()
        server.handle(clock.now())
        assert server.connection_count == 0

    def test_pending_connection_creates_connection_object(self):
        server, listener, clock = _make_server()
        peer = FakeSocket()
        listener.queue_accept(peer)
        server.handle(clock.now())
        assert server.connection_count == 1

    def test_max_connections_limit_respected(self):
        server, listener, clock = _make_server(max_connections=2)
        for _index in range(5):
            listener.queue_accept(FakeSocket())
        server.handle(clock.now())
        assert server.connection_count == 2

    def test_listener_error_does_not_raise(self):
        server, listener, clock = _make_server()
        original_accept = listener.accept

        def _raise(*_args, **_kwargs):
            raise OSError(99, "listener dead")

        listener.accept = _raise
        server.handle(clock.now())
        assert server.connection_count == 0
        listener.accept = original_accept


# ---------------------------------------------------------------------------
# Handshake — happy path
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Handshake — rejections
# ---------------------------------------------------------------------------


class TestHandshakeRejection:
    def test_malformed_request_returns_400(self):
        server, listener, clock = _make_server()
        peer = FakeSocket()
        listener.queue_accept(peer)
        peer.feed_inbound(b"POST / HTTP/1.1\r\n\r\n")
        server.handle(clock.now())
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
        server.handle(clock.now())
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
        server.handle(clock.now())
        clock.advance(1500)
        server.handle(clock.now())
        # Connection finalized; removed from the active list.
        assert server.connection_count == 0
        assert peer.closed is True

    def test_client_eof_mid_handshake(self):
        server, listener, clock = _make_server()
        peer = FakeSocket()
        listener.queue_accept(peer)
        peer.close_inbound()
        server.handle(clock.now())
        assert server.connection_count == 0

    def test_on_connection_raise_kills_connection(self):
        def boom(_conn):
            raise RuntimeError("user policy rejected")

        server, listener, clock = _make_server(on_connection=boom)
        peer = FakeSocket()
        listener.queue_accept(peer)
        peer.feed_inbound(_client_handshake_bytes())
        server.handle(clock.now())
        # Drive sending the 101 + entering OPEN (which fires callback that raises).
        for _tick in range(5):
            if server.connection_count == 0:
                break
            server.handle(clock.now())
        assert server.connection_count == 0
        assert peer.closed is True


# ---------------------------------------------------------------------------
# OPEN — send/recv
# ---------------------------------------------------------------------------


class TestSendReceive:
    def test_inbound_text_unmasks_and_fires_callback(self):
        observed = []

        def on_open(conn):
            conn.on_text = lambda text: observed.append(("text", text))

        server, listener, clock = _make_server(on_connection=on_open)
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_TEXT, b"hello"))
        server.handle(clock.now())
        assert observed == [("text", "hello")]

    def test_inbound_binary_fires_callback(self):
        observed = []

        def on_open(conn):
            conn.on_binary = lambda data: observed.append(("bin", data))

        server, listener, clock = _make_server(on_connection=on_open)
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_BINARY, b"\x00\x01\x02"))
        server.handle(clock.now())
        assert observed == [("bin", b"\x00\x01\x02")]

    def test_unmasked_inbound_frame_closes_with_protocol_error(self):
        server, listener, clock = _make_server()
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        # Server expects MASK bit set on inbound; sending a server-style frame
        # (no mask) is a protocol violation.
        peer.feed_inbound(encode_frame(OPCODE_TEXT, b"hi", mask=None))
        server.handle(clock.now())
        # Connection finalizes after draining the close.
        for _tick in range(3):
            if server.connection_count == 0:
                break
            server.handle(clock.now())
        # Server's outbound close frame was sent before tear-down.
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.opcode == OPCODE_CLOSE
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_PROTOCOL_ERROR

    def test_send_text_pre_open_raises(self):
        # Build a Connection in CONNECTING state via direct construction.
        clock = TickClock()
        peer = FakeSocket()
        connection = Connection(
            peer,
            accept_path=None,
            max_message_bytes=1024,
            recv_budget_per_tick=64,
            send_budget_per_tick=64,
            max_tx_queue_size=4,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
            pong_timeout_ms=5000,
            handshake_timeout_ms=5000,
            close_timeout_ms=5000,
            ticks_ms_func=clock.now,
            ticks_add_func=clock.add,
            ticks_diff_func=clock.diff,
            on_connection_callback=lambda _c: None,
        )
        with raises(WebSocketStateError, match="OPEN"):
            connection.send_text("hi")
        with raises(WebSocketStateError, match="OPEN"):
            connection.send_binary(b"hi")
        with raises(WebSocketStateError, match="OPEN"):
            connection.send_ping()

    def test_send_binary_rejects_non_bytes(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        _drive_server_handshake(server, listener, clock)
        with raises(TypeError):
            observed[0].send_binary(["not", "bytes"])

    def test_outbound_text_is_unmasked(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        observed[0].send_text("hello")
        server.handle(clock.now())
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.opcode == OPCODE_TEXT
        assert parser.had_mask is False
        assert parser.payload == b"hello"

    def test_outbound_binary_accepts_bytearray(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        observed[0].send_binary(bytearray(b"abc"))
        server.handle(clock.now())
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.payload == b"abc"

    def test_backpressure_when_queue_full(self):
        observed = []
        server, listener, clock = _make_server(
            max_tx_queue_size=2,
            on_connection=lambda connection: observed.append(connection),
        )
        _drive_server_handshake(server, listener, clock)
        observed[0].send_text("a")
        observed[0].send_text("b")
        with raises(WebSocketBackpressureError):
            observed[0].send_text("c")

    def test_invalid_utf8_text_closes(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_TEXT, b"\xff\xfe"))
        server.handle(clock.now())
        # Drain close.
        for _tick in range(3):
            if server.connection_count == 0:
                break
            server.handle(clock.now())
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_BAD_DATA


# ---------------------------------------------------------------------------
# Fragmentation
# ---------------------------------------------------------------------------


class TestFragmentation:
    def test_fragmented_text_reassembles(self):
        observed = []

        def on_open(conn):
            conn.on_text = lambda text: observed.append(text)

        server, listener, clock = _make_server(on_connection=on_open)
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(
            encode_frame(OPCODE_TEXT, b"hel", fin=False, mask=make_mask_key())
            + encode_frame(OPCODE_CONTINUATION, b"lo!", fin=True, mask=make_mask_key()),
        )
        server.handle(clock.now())
        server.handle(clock.now())
        assert observed == ["hello!"]

    def test_continuation_with_no_in_progress_closes(self):
        server, listener, clock = _make_server()
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_CONTINUATION, b"orphan"))
        server.handle(clock.now())
        for _tick in range(3):
            if server.connection_count == 0:
                break
            server.handle(clock.now())
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_PROTOCOL_ERROR


# ---------------------------------------------------------------------------
# Control frames
# ---------------------------------------------------------------------------


class TestControlFrames:
    def test_inbound_ping_triggers_pong(self):
        observed = []

        def on_open(conn):
            conn.on_ping = lambda payload: observed.append(payload)

        server, listener, clock = _make_server(on_connection=on_open)
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_PING, b"pingdata"))
        server.handle(clock.now())
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.opcode == OPCODE_PONG
        assert parser.payload == b"pingdata"
        assert observed == [b"pingdata"]

    def test_pong_clears_pending_deadline(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        connection = observed[0]
        connection.send_ping(b"hb")
        server.handle(clock.now())
        peer.read_outbound()
        assert connection._pending_ping_deadline_ticks is not None
        peer.feed_inbound(_server_frame(OPCODE_PONG, b"hb"))
        server.handle(clock.now())
        assert connection._pending_ping_deadline_ticks is None


# ---------------------------------------------------------------------------
# Close handshake
# ---------------------------------------------------------------------------


class TestCloseHandshake:
    def test_server_initiated_close(self):
        observed = []
        closes = []

        def on_open(conn):
            conn.on_close = lambda code, reason: closes.append((code, reason))

        server, listener, clock = _make_server(
            on_connection=lambda connection: (observed.append(connection), on_open(connection)),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        connection = observed[0]
        connection.close(CLOSE_GOING_AWAY, "going down")
        # Drain server-side close frame.
        server.handle(clock.now())
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.opcode == OPCODE_CLOSE
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_GOING_AWAY
        # Peer echoes close.
        peer.feed_inbound(
            _server_frame(OPCODE_CLOSE, encode_close_payload(CLOSE_GOING_AWAY, "ok")),
        )
        server.handle(clock.now())
        assert connection.state == WebSocketState.CLOSED
        assert closes == [(CLOSE_GOING_AWAY, "going down")]

    def test_client_initiated_close_echoed(self):
        observed = []
        closes = []

        def on_open(connection):
            observed.append(connection)
            connection.on_close = lambda code, reason: closes.append((code, reason))

        server, listener, clock = _make_server(on_connection=on_open)
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(
            _server_frame(OPCODE_CLOSE, encode_close_payload(CLOSE_GOING_AWAY, "client gone")),
        )
        server.handle(clock.now())
        # Drain echo.
        server.handle(clock.now())
        connection = observed[0]
        assert connection.state == WebSocketState.CLOSED
        assert connection.last_close_code == CLOSE_GOING_AWAY
        assert connection.last_close_reason == "client gone"
        assert closes == [(CLOSE_GOING_AWAY, "client gone")]

    def test_close_in_closing_or_closed_raises(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        _drive_server_handshake(server, listener, clock)
        connection = observed[0]
        connection.close()
        with raises(WebSocketStateError):
            connection.close()

    def test_close_timeout_forces_finalize(self):
        observed = []
        server, listener, clock = _make_server(
            close_timeout_ms=1000,
            on_connection=lambda connection: observed.append(connection),
        )
        _drive_server_handshake(server, listener, clock)
        connection = observed[0]
        connection.close()
        server.handle(clock.now())  # drain close frame
        clock.advance(1500)
        server.handle(clock.now())
        assert connection.state == WebSocketState.CLOSED

    def test_close_with_invalid_payload_falls_back_to_empty(self):
        from chumicro_websockets._wire import CLOSE_ABNORMAL
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        observed[0].close(CLOSE_ABNORMAL, "")
        server.handle(clock.now())
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.opcode == OPCODE_CLOSE
        assert parser.payload == b""

    def test_inbound_close_with_invalid_body(self):
        server, listener, clock = _make_server()
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_CLOSE, b"\x03"))  # 1-byte forbidden
        server.handle(clock.now())
        for _tick in range(3):
            if server.connection_count == 0:
                break
            server.handle(clock.now())
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_PROTOCOL_ERROR

    def test_client_eof_post_open_is_protocol_error(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.close_inbound()
        server.handle(clock.now())
        connection = observed[0]
        assert connection.state == WebSocketState.CLOSED
        assert "without sending a CLOSE frame" in str(connection.last_error)


# ---------------------------------------------------------------------------
# Oversize policy
# ---------------------------------------------------------------------------


class TestOversize:
    def test_drop_with_event_fires_and_closes(self):
        observed = []
        oversized = []

        def on_open(conn):
            conn.on_oversized = lambda length: oversized.append(length)

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
        server.handle(clock.now())
        server.handle(clock.now())
        assert oversized
        # Drain close.
        for _tick in range(3):
            if server.connection_count == 0:
                break
            server.handle(clock.now())
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_TOO_BIG

    def test_drop_silent(self):
        oversized = []

        def on_open(conn):
            conn.on_oversized = lambda length: oversized.append(length)

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
        server.handle(clock.now())
        server.handle(clock.now())
        assert oversized == []
        # Connection still OPEN.
        assert server.connections[0].state == WebSocketState.OPEN

    def test_disconnect(self):
        oversized = []
        observed = []

        def on_open(connection):
            observed.append(connection)
            connection.on_oversized = lambda length: oversized.append(length)

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
        server.handle(clock.now())
        server.handle(clock.now())
        assert oversized == []  # DISCONNECT does NOT fire on_oversized
        # Connection transitioned to CLOSING; peer echoes close to finalize.
        assert observed[0].state in (WebSocketState.CLOSING, WebSocketState.CLOSED)


# ---------------------------------------------------------------------------
# Server.close()
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Connection-level edges (drives Connection directly)
# ---------------------------------------------------------------------------


class TestConnectionEdges:
    def test_handshake_send_eagain_keeps_state(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer = FakeSocket()
        listener.queue_accept(peer)
        peer.feed_inbound(_client_handshake_bytes())
        server.handle(clock.now())  # accepts + reads request + transitions to SENDING_RESPONSE
        peer.raise_on_send = OSError(11, "would block")
        server.handle(clock.now())  # send EAGAIN — state unchanged
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
        server.handle(clock.now())
        peer.raise_on_send = OSError(99, "send dead")
        server.handle(clock.now())
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
        server.handle(clock.now())
        assert observed[0].state == WebSocketState.CLOSED

    def test_send_error_in_open_finalizes(self):
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        observed[0].send_text("hello")
        peer.raise_on_send = OSError(99, "send dead")
        server.handle(clock.now())
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
        observed[0]._state = WebSocketState.CLOSED
        assert observed[0].check(clock.now()) is False

    def test_pong_overdue_finalizes(self):
        observed = []
        server, listener, clock = _make_server(
            pong_timeout_ms=1000,
            on_connection=lambda connection: observed.append(connection),
        )
        _drive_server_handshake(server, listener, clock)
        observed[0].send_ping(b"hb")
        server.handle(clock.now())
        clock.advance(1500)
        server.handle(clock.now())
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
            server.handle(clock.now())
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
        server.handle(clock.now())  # reach SENDING_RESPONSE
        # Patch send to return 0 transiently.
        original_send = peer.send
        peer.send = lambda _data: 0
        server.handle(clock.now())
        connection = server.connections[0]
        assert connection.state == WebSocketState.CONNECTING
        peer.send = original_send


# ---------------------------------------------------------------------------
# from_config — config-aware construction
# ---------------------------------------------------------------------------


class TestServerFromConfig:
    """``WebSocketServer.from_config`` reads the server-side keys from
    the ``[tool.chumicro.config]`` manifest with sensible defaults.
    All optional — defaults to ``0.0.0.0:8765`` with the library's
    default ``max_message_bytes``.

    Like ntp's from_config (and unlike mqtt's), no key is required —
    a sensible bind target exists when none is supplied.  ``listener=``
    overrides the auto-built listener; ``on_connection`` is required
    positional because it's a callback the user must provide."""

    def test_reads_max_message_bytes_from_config(self) -> None:
        listener = FakeListener()
        server = WebSocketServer.from_config(
            {"websockets.server.max_message_bytes": 4096},
            _noop_connection,
            listener=listener,
        )
        assert server._max_message_bytes == 4096  # noqa: SLF001
        assert server._listener is listener  # noqa: SLF001

    def test_defaults_apply_when_keys_absent(self) -> None:
        """Empty config → max_message_bytes falls back to library default."""
        from chumicro_websockets._wire import DEFAULT_MAX_MESSAGE_BYTES
        listener = FakeListener()
        server = WebSocketServer.from_config(
            {}, _noop_connection, listener=listener,
        )
        assert server._max_message_bytes == DEFAULT_MAX_MESSAGE_BYTES  # noqa: SLF001

    def test_explicit_listener_bypasses_auto_built(self) -> None:
        """Passing listener= skips the chumicro_sockets.tcp_listening_socket
        path entirely — caller owns the bind/listen behaviour."""
        listener = FakeListener()
        server = WebSocketServer.from_config(
            {
                "websockets.server.host": "ignored.test",
                "websockets.server.port": 9999,
            },
            _noop_connection,
            listener=listener,
        )
        assert server._listener is listener  # noqa: SLF001

    def test_runtime_config_wrapper_works_too(self) -> None:
        """Real ``RuntimeConfig`` instance — same flat-key reads as a dict."""
        from chumicro_config import RuntimeConfig
        listener = FakeListener()
        config = RuntimeConfig({"websockets.server.max_message_bytes": 8192})
        server = WebSocketServer.from_config(
            config, _noop_connection, listener=listener,
        )
        assert server._max_message_bytes == 8192  # noqa: SLF001

    def test_auto_listener_threads_host_port_and_radio(self) -> None:
        """When no listener is passed, ``from_config`` builds one via
        ``chumicro_sockets.tcp_listening_socket(host, port, radio=...)``
        using config-supplied host/port (or the library defaults)."""
        import chumicro_sockets as sockets_mod

        listener = FakeListener()
        captured: dict = {}

        def fake_tcp_listening_socket(host, port, *, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["radio"] = radio
            return listener

        original = sockets_mod.tcp_listening_socket
        sockets_mod.tcp_listening_socket = fake_tcp_listening_socket
        try:
            server = WebSocketServer.from_config(
                {
                    "websockets.server.host": "10.0.0.7",
                    "websockets.server.port": 8443,
                },
                _noop_connection,
                radio="fake-radio",
            )
        finally:
            sockets_mod.tcp_listening_socket = original

        assert captured == {
            "host": "10.0.0.7", "port": 8443, "radio": "fake-radio",
        }
        assert server._listener is listener  # noqa: SLF001

    def test_auto_listener_falls_back_to_library_defaults(self) -> None:
        """Empty config → bind to 0.0.0.0:8765 (library-convention port)."""
        import chumicro_sockets as sockets_mod

        listener = FakeListener()
        captured: dict = {}

        def fake_tcp_listening_socket(host, port, *, radio=None):
            captured["host"] = host
            captured["port"] = port
            return listener

        original = sockets_mod.tcp_listening_socket
        sockets_mod.tcp_listening_socket = fake_tcp_listening_socket
        try:
            WebSocketServer.from_config({}, _noop_connection)
        finally:
            sockets_mod.tcp_listening_socket = original

        assert captured == {"host": "0.0.0.0", "port": 8765}

    def test_accept_path_kwarg_passes_through(self) -> None:
        """accept_path is a per-deploy app-routing knob, not a config
        manifest key.  from_config still accepts it as a kwarg."""
        listener = FakeListener()
        server = WebSocketServer.from_config(
            {}, _noop_connection,
            listener=listener,
            accept_path="/echo",
        )
        assert server._accept_path == "/echo"  # noqa: SLF001
