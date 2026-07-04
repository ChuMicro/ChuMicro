"""WebSocket client tests (chumicro_websockets.client): control
frames and the close handshake."""

import struct

from _client_helpers import (
    _client_frame,
    _drive_handshake,
    _make_client,
)
from chumicro_test_harness.assertions import raises
from chumicro_websockets import (
    CLOSE_GOING_AWAY,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    OPCODE_CLOSE,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    WebSocketState,
    WebSocketStateError,
    WebSocketTimeoutError,
)
from chumicro_websockets._wire import (
    FrameParser,
    FrameParseState,
    encode_close_payload,
)


class TestControlFrames:
    def test_ping_triggers_pong_and_callback(self):
        client, socket, clock, _ = _make_client()
        pings = []
        client.on_ping = lambda payload: pings.append(payload)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(_client_frame(OPCODE_PING, b"pingdata"))
        client.handle(clock.ticks_ms())  # processes inbound + drains pong
        assert pings == [b"pingdata"]
        outbound = socket.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.opcode == OPCODE_PONG
        assert parser.payload == b"pingdata"

    def test_pong_clears_pending_deadline_and_fires_callback(self):
        client, socket, clock, _ = _make_client()
        pongs = []
        client.on_pong = lambda payload: pongs.append(payload)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.send_ping(b"heartbeat")
        client.handle(clock.ticks_ms())  # drain outbound ping
        assert client._pending_ping_deadline_ticks is not None
        socket.read_outbound()
        socket.feed_inbound(_client_frame(OPCODE_PONG, b"heartbeat"))
        client.handle(clock.ticks_ms())
        assert pongs == [b"heartbeat"]
        assert client._pending_ping_deadline_ticks is None

    def test_send_ping_payload_too_long_raises(self):
        from chumicro_websockets import WebSocketProtocolError
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        with raises(WebSocketProtocolError, match="125"):
            client.send_ping(b"X" * 200)


class TestCloseHandshake:
    def test_inbound_after_protocol_error_does_not_wedge(self):
        # A reserved-opcode frame makes the parser latch ERROR and the
        # session send CLOSE; when the peer's CLOSE echo then arrives,
        # feeding it to the wedged parser must not spin handle() forever
        # (the parser consumes nothing in ERROR).
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(b"\x83\x00")  # FIN=1, reserved opcode 0x3, len 0
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSING
        socket.feed_inbound(
            _client_frame(OPCODE_CLOSE, encode_close_payload(CLOSE_NORMAL, "")),
        )
        client.handle(clock.ticks_ms())  # returns instead of hanging
        assert client.state in (WebSocketState.CLOSING, WebSocketState.CLOSED)

    def test_ping_flood_does_not_evict_queued_user_frames(self):
        # Internal PONGs bypass the user cap into headroom, but a flood
        # must never evict a queued user frame (CPython deque overflow)
        # or crash (MP/CP raise on a full flags=1 deque).  All queued
        # user texts must still reach the wire.
        client, socket, clock, _ = _make_client(max_tx_queue_size=3)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.send_text("alpha")
        client.send_text("bravo")
        client.send_text("charlie")
        # 30 pings in one inbound chunk -> 30 PONGs contend for headroom.
        flood = b"".join(_client_frame(OPCODE_PING, b"") for _ in range(30))
        socket.feed_inbound(flood)
        for _ in range(80):
            client.handle(clock.ticks_ms())
        # Outbound frames are client-masked; parse + unmask to collect texts.
        sent = socket.read_outbound()
        texts = []
        parser = FrameParser()
        offset = 0
        while offset < len(sent):
            offset += parser.feed(sent, offset)
            if parser.state == FrameParseState.FRAME_READY:
                if parser.opcode == OPCODE_TEXT:
                    texts.append(bytes(parser.payload))
                parser.reset()
            else:
                break
        assert b"alpha" in texts
        assert b"bravo" in texts
        assert b"charlie" in texts

    def test_close_sends_close_frame_and_transitions(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.close(CLOSE_GOING_AWAY, "bye")
        assert client.state == WebSocketState.CLOSING
        client.handle(clock.ticks_ms())
        sent = socket.read_outbound()
        parser = FrameParser()
        parser.feed(sent)
        assert parser.opcode == OPCODE_CLOSE
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_GOING_AWAY
        assert parser.payload[2:] == b"bye"

    def test_peer_close_during_closing_finalizes(self):
        client, socket, clock, _ = _make_client()
        closes = []
        client.on_close = lambda code, reason: closes.append((code, reason))
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.close(CLOSE_NORMAL, "bye")
        client.handle(clock.ticks_ms())  # drain our close frame
        socket.read_outbound()
        # Peer's close echo.
        socket.feed_inbound(
            _client_frame(OPCODE_CLOSE, encode_close_payload(CLOSE_NORMAL, "ok")),
        )
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert client.last_close_code == CLOSE_NORMAL
        assert closes == [(CLOSE_NORMAL, "bye")]
        assert socket.closed is True

    def test_peer_initiated_close_echoes_back(self):
        client, socket, clock, _ = _make_client()
        closes = []
        client.on_close = lambda code, reason: closes.append((code, reason))
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(
            _client_frame(
                OPCODE_CLOSE,
                encode_close_payload(CLOSE_GOING_AWAY, "server going down"),
            ),
        )
        client.handle(clock.ticks_ms())
        # Echo close was queued.  One more handle drains it.
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert client.last_close_code == CLOSE_GOING_AWAY
        assert client.last_close_reason == "server going down"
        assert closes == [(CLOSE_GOING_AWAY, "server going down")]

    def test_close_in_closed_state_raises(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.close()
        # Force into CLOSED.
        socket.feed_inbound(
            _client_frame(OPCODE_CLOSE, encode_close_payload(CLOSE_NORMAL, "")),
        )
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        with raises(WebSocketStateError):
            client.close()

    def test_close_timeout_forces_closed(self):
        client, socket, clock, _ = _make_client(close_timeout_ms=1000)
        closes = []
        client.on_close = lambda code, reason: closes.append((code, reason))
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.close(CLOSE_NORMAL, "bye")
        client.handle(clock.ticks_ms())  # drain close
        clock.advance(1500)
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert isinstance(client.last_error, WebSocketTimeoutError)
        assert closes  # on_close still fired

    def test_invalid_close_payload_falls_back_to_empty(self):
        from chumicro_websockets._wire import CLOSE_ABNORMAL
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        # CLOSE_ABNORMAL (1006) is reserved, so encode_close_payload raises.
        # The client falls back to empty body so the close still proceeds.
        client.close(CLOSE_ABNORMAL, "")
        client.handle(clock.ticks_ms())
        sent = socket.read_outbound()
        parser = FrameParser()
        parser.feed(sent)
        assert parser.opcode == OPCODE_CLOSE
        assert parser.payload == b""

    def test_inbound_close_with_invalid_payload(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        # Invalid: 1-byte close payload (RFC §5.5.1 forbids).
        socket.feed_inbound(b"\x88\x01\x03")
        client.handle(clock.ticks_ms())
        # Client closes with PROTOCOL_ERROR.
        assert client.state == WebSocketState.CLOSING
        client.handle(clock.ticks_ms())
        sent = socket.read_outbound()
        parser = FrameParser()
        parser.feed(sent)
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_PROTOCOL_ERROR
