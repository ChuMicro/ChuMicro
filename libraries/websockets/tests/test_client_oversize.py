"""WebSocket client tests (chumicro_websockets.client): message-level
and frame-level oversize handling."""

from _client_helpers import (
    _drive_handshake,
    _make_client,
)
from chumicro_websockets import (
    CLOSE_TOO_BIG,
    OPCODE_CONTINUATION,
    OPCODE_TEXT,
    WebSocketState,
    WhenOversized,
)
from chumicro_websockets._wire import encode_frame


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
