"""WebSocket server tests (chumicro_websockets.server): send/receive,
fragmentation, control frames, close handshake."""

import struct

from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    CLOSE_BAD_DATA,
    CLOSE_GOING_AWAY,
    CLOSE_PROTOCOL_ERROR,
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
    WhenOversized,
    make_websocket_key,
)
from chumicro_websockets._wire import (
    FrameParser,
    encode_client_handshake,
    encode_close_payload,
    encode_frame,
    make_mask_key,
)
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

def _server_frame(opcode: int, payload: bytes) -> bytes:
    """Encode a client→server frame (masked) for inbound feeding."""
    return encode_frame(opcode, payload, fin=True, mask=make_mask_key())


class TestSendReceive:
    def test_inbound_text_unmasks_and_fires_callback(self):
        observed = []

        def on_open(conn):
            conn.on_text = lambda text: observed.append(("text", text))

        server, listener, clock = _make_server(on_connection=on_open)
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_TEXT, b"hello"))
        server.handle(clock.ticks_ms())
        assert observed == [("text", "hello")]

    def test_inbound_binary_fires_callback(self):
        observed = []

        def on_open(conn):
            conn.on_binary = lambda data: observed.append(("bin", data))

        server, listener, clock = _make_server(on_connection=on_open)
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_BINARY, b"\x00\x01\x02"))
        server.handle(clock.ticks_ms())
        assert observed == [("bin", b"\x00\x01\x02")]

    def test_unmasked_inbound_frame_closes_with_protocol_error(self):
        server, listener, clock = _make_server()
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        # Server expects MASK bit set on inbound.  Sending a server-style
        # frame (no mask) is a protocol violation.
        peer.feed_inbound(encode_frame(OPCODE_TEXT, b"hi", mask=None))
        server.handle(clock.ticks_ms())
        # Connection finalizes after draining the close.
        for _tick in range(3):
            if server.connection_count == 0:
                break
            server.handle(clock.ticks_ms())
        # Server's outbound close frame was sent before tear-down.
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.opcode == OPCODE_CLOSE
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_PROTOCOL_ERROR

    def test_send_text_pre_open_raises(self):
        # Build a Connection in CONNECTING state via direct construction.
        clock = FakeTicks()
        peer = FakeSocket()
        connection = Connection(
            peer,
            clock.ticks_ms(),
            accept_path=None,
            max_message_bytes=1024,
            recv_budget_per_tick=64,
            send_budget_per_tick=64,
            max_tx_queue_size=4,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
            pong_timeout_ms=5000,
            handshake_timeout_ms=5000,
            close_timeout_ms=5000,
            ticks=clock,
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
        server.handle(clock.ticks_ms())
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
        server.handle(clock.ticks_ms())
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
        server.handle(clock.ticks_ms())
        # Drain close.
        for _tick in range(3):
            if server.connection_count == 0:
                break
            server.handle(clock.ticks_ms())
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_BAD_DATA


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
        server.handle(clock.ticks_ms())
        server.handle(clock.ticks_ms())
        assert observed == ["hello!"]

    def test_continuation_with_no_in_progress_closes(self):
        server, listener, clock = _make_server()
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_CONTINUATION, b"orphan"))
        server.handle(clock.ticks_ms())
        for _tick in range(3):
            if server.connection_count == 0:
                break
            server.handle(clock.ticks_ms())
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_PROTOCOL_ERROR


class TestServerCloseFromCallback:
    def test_close_inside_connection_callback_does_not_raise(self):
        # A connection callback that calls server.close() clears every
        # connection; handle() must not then try to remove an entry that
        # is already gone.
        events = []

        def on_open(conn):
            def on_text(text):
                events.append(text)
                server_box["server"].close()
            conn.on_text = on_text

        server_box = {}
        server, listener, clock = _make_server(on_connection=on_open)
        server_box["server"] = server
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_TEXT, b"shutdown"))
        server.handle(clock.ticks_ms())  # no ValueError from list.remove
        assert events == ["shutdown"]
        assert server.closed is True
        assert server.connection_count == 0

    def test_callback_exception_resets_parser_no_redeliver_or_wedge(self):
        # A user callback raising mid-dispatch must not leave the parser
        # in FRAME_READY: the frame must not be redelivered, and the next
        # frame must still parse (a stuck FRAME_READY parser consumes 0).
        calls = []

        def on_open(conn):
            def on_text(text):
                calls.append(text)
                if text == "boom":
                    raise ValueError("handler blew up")
            conn.on_text = on_text

        server, listener, clock = _make_server(on_connection=on_open)
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_TEXT, b"boom"))
        with raises(ValueError):
            server.handle(clock.ticks_ms())  # callback raises, propagates
        peer.feed_inbound(_server_frame(OPCODE_TEXT, b"next"))
        server.handle(clock.ticks_ms())
        assert calls == ["boom", "next"]


class TestControlFrames:
    def test_inbound_ping_triggers_pong(self):
        observed = []

        def on_open(conn):
            conn.on_ping = lambda payload: observed.append(payload)

        server, listener, clock = _make_server(on_connection=on_open)
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_PING, b"pingdata"))
        server.handle(clock.ticks_ms())
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
        server.handle(clock.ticks_ms())
        peer.read_outbound()
        assert connection._pending_ping_deadline_ticks is not None
        peer.feed_inbound(_server_frame(OPCODE_PONG, b"hb"))
        server.handle(clock.ticks_ms())
        assert connection._pending_ping_deadline_ticks is None


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
        server.handle(clock.ticks_ms())
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
        server.handle(clock.ticks_ms())
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
        server.handle(clock.ticks_ms())
        # Drain echo.
        server.handle(clock.ticks_ms())
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
        server.handle(clock.ticks_ms())  # drain close frame
        clock.advance(1500)
        server.handle(clock.ticks_ms())
        assert connection.state == WebSocketState.CLOSED

    def test_close_with_invalid_payload_falls_back_to_empty(self):
        from chumicro_websockets._wire import CLOSE_ABNORMAL
        observed = []
        server, listener, clock = _make_server(
            on_connection=lambda connection: observed.append(connection),
        )
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        observed[0].close(CLOSE_ABNORMAL, "")
        server.handle(clock.ticks_ms())
        outbound = peer.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.opcode == OPCODE_CLOSE
        assert parser.payload == b""

    def test_inbound_close_with_invalid_body(self):
        server, listener, clock = _make_server()
        peer, _key, _response = _drive_server_handshake(server, listener, clock)
        peer.feed_inbound(_server_frame(OPCODE_CLOSE, b"\x03"))  # 1-byte forbidden
        server.handle(clock.ticks_ms())
        for _tick in range(3):
            if server.connection_count == 0:
                break
            server.handle(clock.ticks_ms())
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
        server.handle(clock.ticks_ms())
        connection = observed[0]
        assert connection.state == WebSocketState.CLOSED
        assert "without sending a CLOSE frame" in str(connection.last_error)
