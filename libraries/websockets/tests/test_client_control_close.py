"""WebSocket client tests (chumicro_websockets.client): control
frames, close handshake, oversize and frame-level oversize."""

import struct

from chumicro_sockets.testing import FakeSocketConnector
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    CLOSE_GOING_AWAY,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    CLOSE_TOO_BIG,
    OPCODE_CLOSE,
    OPCODE_CONTINUATION,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    WebSocketClient,
    WebSocketState,
    WebSocketStateError,
    WebSocketTimeoutError,
    WhenOversized,
    derive_accept_key,
)
from chumicro_websockets._wire import (
    FrameParser,
    FrameParseState,
    HandshakeRequestParser,
    encode_close_payload,
    encode_frame,
)
from chumicro_websockets.client import ConnectingPhase
from chumicro_websockets.testing import FakeConnection

FakeSocket = FakeConnection

def _make_factory(socket: FakeConnection, *, expected_use_tls: bool | None = None):
    """Connector-factory closure that records its args + returns a
    scripted ``FakeSocketConnector`` wrapping *socket*."""
    record = {"calls": []}

    def factory(host, port, use_tls):
        record["calls"].append((host, port, use_tls))
        if expected_use_tls is not None:
            assert use_tls is expected_use_tls
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=socket)

    return factory, record

def _drive_handshake(
    client: WebSocketClient,
    socket: FakeSocket,
    clock: FakeTicks,
) -> bytes:
    """Push ticks until AWAITING_TRANSPORT + SENDING_HANDSHAKE finish, then craft + feed a 101.

    Returns the request bytes the client wrote so callers can assert on
    them (``Sec-WebSocket-Key`` etc.).  Leaves the client OPEN.
    """
    # Drain AWAITING_TRANSPORT (connector ticks) + SENDING_HANDSHAKE.
    while client.state == WebSocketState.CONNECTING and (
        client._connecting_phase
        in (ConnectingPhase.AWAITING_TRANSPORT, ConnectingPhase.SENDING_HANDSHAKE)
    ):
        client.handle(clock.ticks_ms())
    request_bytes = socket.read_outbound()
    # Parse the request to get the client's key.
    parser = HandshakeRequestParser()
    parser.feed(request_bytes)
    accept_token = derive_accept_key(parser.client_key)
    response = (
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: " + accept_token.encode("ascii") + b"\r\n"
        b"\r\n"
    )
    socket.feed_inbound(response)
    # Drive once to consume + transition to OPEN.
    client.handle(clock.ticks_ms())
    return request_bytes

def _make_client(
    *,
    socket: FakeSocket | None = None,
    clock: FakeTicks | None = None,
    **kwargs,
):
    """Construct a client wired to a fresh fake socket + clock."""
    if socket is None:
        socket = FakeSocket()
    if clock is None:
        clock = FakeTicks()
    factory, record = _make_factory(socket)
    client = WebSocketClient(
        connector_factory=factory,
        ticks=clock,
        **kwargs,
    )
    return client, socket, clock, record

def _client_frame(opcode: int, payload: bytes) -> bytes:
    """Encode a server→client frame (no mask) for inbound feeding."""
    return encode_frame(opcode, payload, fin=True, mask=None)


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


class TestOversize:
    def test_drop_silent_does_not_close(self):
        client, socket, clock, _ = _make_client(
            max_message_bytes=10,
            when_oversized=WhenOversized.DROP_SILENT,
        )
        oversized = []
        client.on_oversized = lambda reported_length: oversized.append(reported_length)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        # Two-frame fragmented message exceeding cap 10.
        socket.feed_inbound(
            encode_frame(OPCODE_TEXT, b"01234", fin=False, mask=None)
            + encode_frame(OPCODE_CONTINUATION, b"567890123", fin=True, mask=None),
        )
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        assert oversized == []
        assert client.state == WebSocketState.OPEN

    def test_drop_with_event_fires_callback_and_stays_open(self):
        client, socket, clock, _ = _make_client(
            max_message_bytes=10,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
        )
        oversized = []
        client.on_oversized = lambda reported_length: oversized.append(reported_length)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(
            encode_frame(OPCODE_TEXT, b"01234", fin=False, mask=None)
            + encode_frame(OPCODE_CONTINUATION, b"5678901234", fin=True, mask=None),
        )
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        assert oversized
        assert client.state == WebSocketState.OPEN

    def test_drop_with_event_next_message_arrives_intact(self):
        """After an oversized message is dropped, the framing stream stays
        aligned and the very next message is delivered to ``on_text``.

        Drains a 3-frame oversized assembly followed immediately by a
        single normal frame — all queued on the socket at once so any
        leftover byte misalignment in the parser would corrupt the next
        message's header.
        """
        client, socket, clock, _ = _make_client(
            max_message_bytes=10,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
        )
        received = []
        oversized = []
        client.on_text = lambda text: received.append(text)
        client.on_oversized = lambda reported_length: oversized.append(reported_length)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(
            # Oversized assembly: 5 + 5 + 5 = 15 bytes, cap is 10.
            encode_frame(OPCODE_TEXT, b"AAAAA", fin=False, mask=None)
            + encode_frame(OPCODE_CONTINUATION, b"BBBBB", fin=False, mask=None)
            + encode_frame(OPCODE_CONTINUATION, b"CCCCC", fin=True, mask=None)
            # Next message: should arrive intact if drain + framing held.
            + encode_frame(OPCODE_TEXT, b"hello", fin=True, mask=None),
        )
        for _index in range(6):
            client.handle(clock.ticks_ms())
        assert oversized, "on_oversized never fired"
        assert client.state == WebSocketState.OPEN, (
            f"expected OPEN, got {client.state}"
        )
        assert received == ["hello"], (
            f"next message lost or corrupted; got {received!r}"
        )

    def test_drop_with_event_drain_across_recv_chunk_boundaries(self):
        """Force the oversize payload + next message to span multiple
        ``recv_into`` calls by overrunning the 512-byte recv buffer.

        Real TCP delivers bytes in arbitrary chunks; the parser must
        hold state correctly across recvs so that draining a partial
        frame and starting the next one falls on the right header byte.
        """
        client, socket, clock, _ = _make_client(
            max_message_bytes=400,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
        )
        received = []
        oversized = []
        client.on_text = lambda text: received.append(text)
        client.on_oversized = lambda reported_length: oversized.append(reported_length)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        # 3 × 200 B fragmented payload = 600 B assembled (> 400 B cap),
        # plus a 50 B normal message.  Wire bytes total > 660 B which
        # exceeds the 512 B recv buffer, so the bytes split across ≥ 2 recvs.
        socket.feed_inbound(
            encode_frame(OPCODE_TEXT, b"A" * 200, fin=False, mask=None)
            + encode_frame(OPCODE_CONTINUATION, b"B" * 200, fin=False, mask=None)
            + encode_frame(OPCODE_CONTINUATION, b"C" * 200, fin=True, mask=None)
            + encode_frame(OPCODE_TEXT, b"after-oversize", fin=True, mask=None),
        )
        for _index in range(8):
            client.handle(clock.ticks_ms())
        assert oversized, "on_oversized never fired"
        assert client.state == WebSocketState.OPEN, (
            f"expected OPEN, got {client.state}"
        )
        assert received == ["after-oversize"], (
            f"next message lost or corrupted; got {received!r}"
        )

    def test_disconnect_policy_closes_immediately(self):
        client, socket, clock, _ = _make_client(
            max_message_bytes=10,
            when_oversized=WhenOversized.DISCONNECT,
        )
        oversized = []
        client.on_oversized = lambda reported_length: oversized.append(reported_length)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(
            encode_frame(OPCODE_TEXT, b"01234", fin=False, mask=None)
            + encode_frame(OPCODE_CONTINUATION, b"5678901234", fin=True, mask=None),
        )
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        assert oversized == []  # DISCONNECT does not fire on_oversized
        assert client.state == WebSocketState.CLOSING


class TestFrameLevelOversize:
    """Frames whose declared length exceeds ``max_message_bytes``
    drain at the frame layer (tier 3 in :class:`FrameParser`).  The
    session applies its ``WhenOversized`` policy on the resulting
    empty frame.
    """

    def test_drop_silent_drains_frame_and_stays_open(self):
        client, socket, clock, _ = _make_client(
            max_message_bytes=100,
            when_oversized=WhenOversized.DROP_SILENT,
        )
        oversized = []
        client.on_oversized = lambda reported_length: oversized.append(reported_length)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        # Single frame, 500 bytes: well over max_message_bytes=100.
        socket.feed_inbound(encode_frame(OPCODE_TEXT, b"X" * 500, fin=True, mask=None))
        for _index in range(6):
            client.handle(clock.ticks_ms())
        assert oversized == []
        assert client.state == WebSocketState.OPEN

    def test_drop_with_event_reports_frame_length(self):
        client, socket, clock, _ = _make_client(
            max_message_bytes=100,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
        )
        oversized = []
        client.on_oversized = lambda reported_length: oversized.append(reported_length)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(encode_frame(OPCODE_TEXT, b"X" * 500, fin=True, mask=None))
        for _index in range(6):
            client.handle(clock.ticks_ms())
        assert oversized == [500]
        assert client.state == WebSocketState.OPEN

    def test_disconnect_closes_with_too_big(self):
        client, socket, clock, _ = _make_client(
            max_message_bytes=100,
            when_oversized=WhenOversized.DISCONNECT,
        )
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(encode_frame(OPCODE_TEXT, b"X" * 500, fin=True, mask=None))
        for _index in range(6):
            client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSING
        # The session-initiated close stamps the local close code on
        # the session before queuing the CLOSE frame.  The outbound
        # frame is masked so the bytes-on-the-wire status field isn't
        # readable without unmasking.
        assert client.last_close_code == CLOSE_TOO_BIG

    def test_normal_message_after_oversize_drain(self):
        # The connection survives a tier-3 drain and the next inbound
        # message parses cleanly — same property the message-level
        # oversize tests check, exercised at the frame layer.
        client, socket, clock, _ = _make_client(
            max_message_bytes=100,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
        )
        received = []
        oversized = []
        client.on_text = lambda text: received.append(text)
        client.on_oversized = lambda reported_length: oversized.append(reported_length)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(
            encode_frame(OPCODE_TEXT, b"X" * 500, fin=True, mask=None)
            + encode_frame(OPCODE_TEXT, b"hello", fin=True, mask=None),
        )
        for _index in range(8):
            client.handle(clock.ticks_ms())
        assert oversized == [500]
        assert received == ["hello"]
        assert client.state == WebSocketState.OPEN
