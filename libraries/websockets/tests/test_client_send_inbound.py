"""WebSocket client tests (chumicro_websockets.client): handshake
timeout, send-state gating, send queue/drain, inbound data,
fragmentation."""

import struct

from _client_helpers import (
    FakeSocket,
    _client_frame,
    _drive_handshake,
    _make_client,
)
from chumicro_test_harness.assertions import raises
from chumicro_websockets import (
    CLOSE_BAD_DATA,
    CLOSE_INTERNAL_ERROR,
    CLOSE_PROTOCOL_ERROR,
    OPCODE_BINARY,
    OPCODE_CONTINUATION,
    OPCODE_TEXT,
    WebSocketBackpressureError,
    WebSocketState,
    WebSocketStateError,
    WebSocketTimeoutError,
)
from chumicro_websockets._wire import (
    FrameParser,
    encode_frame,
)
from chumicro_websockets.client import ConnectingPhase


class TestHandshakeTimeout:
    def test_deadline_elapses(self):
        client, socket, clock, _ = _make_client(handshake_timeout_ms=1000)
        closes = []
        client.on_close = lambda code, reason: closes.append((code, reason))
        client.connect("ws://example.com/")
        # Drain AWAITING_TRANSPORT + SEND phase, then sit in RECEIVING with no inbound.
        while client._connecting_phase in (
            ConnectingPhase.AWAITING_TRANSPORT, ConnectingPhase.SENDING_HANDSHAKE,
        ):
            client.handle(clock.ticks_ms())
        socket.read_outbound()
        clock.advance(1500)
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert isinstance(client.last_error, WebSocketTimeoutError)
        assert closes and closes[0][0] == CLOSE_INTERNAL_ERROR

    def test_per_connect_timeout_override(self):
        client, _socket, _clock, _ = _make_client(handshake_timeout_ms=10000)
        client.connect("ws://example.com/", timeout_ms=500)
        assert client._handshake_deadline_ticks == 500


class TestSendOpenStateGate:
    def test_send_text_pre_open_raises(self):
        client, _socket, _clock, _ = _make_client()
        client.connect("ws://example.com/")
        with raises(WebSocketStateError, match="OPEN"):
            client.send_text("hi")

    def test_send_binary_pre_open_raises(self):
        client, _socket, _clock, _ = _make_client()
        client.connect("ws://example.com/")
        with raises(WebSocketStateError, match="OPEN"):
            client.send_binary(b"hi")

    def test_send_ping_pre_open_raises(self):
        client, _socket, _clock, _ = _make_client()
        client.connect("ws://example.com/")
        with raises(WebSocketStateError, match="OPEN"):
            client.send_ping()

    def test_send_binary_rejects_non_bytes(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        with raises(TypeError, match="send_binary"):
            client.send_binary(["not", "bytes"])

    def test_send_binary_accepts_bytearray(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.send_binary(bytearray(b"hello"))
        client.handle(clock.ticks_ms())
        outbound = socket.read_outbound()
        # Outbound is masked client frame.  Verify by parsing via FrameParser
        # with no mask validation (FrameParser strips the mask).
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.opcode == OPCODE_BINARY
        assert parser.payload == b"hello"

    def test_send_binary_accepts_memoryview(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.send_binary(memoryview(b"abcdef"))
        client.handle(clock.ticks_ms())
        outbound = socket.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.payload == b"abcdef"


class TestSendQueuesAndDrains:
    def test_send_text_writes_masked_text_frame(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.send_text("hello")
        client.handle(clock.ticks_ms())
        outbound = socket.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.opcode == OPCODE_TEXT
        assert parser.had_mask is True
        assert parser.payload == b"hello"

    def test_backpressure_when_queue_full(self):
        client, socket, clock, _ = _make_client(max_tx_queue_size=2)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.send_text("a")
        client.send_text("b")
        with raises(WebSocketBackpressureError, match="TX queue is full"):
            client.send_text("c")

    def test_partial_send_resumes_next_tick(self):
        socket = FakeSocket()
        socket.send_chunk_cap = 4
        client, _socket, clock, _ = _make_client(
            socket=socket,
            send_budget_per_tick=4,
        )
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.send_text("hello world")
        # Drain over multiple handles, each capped at 4 bytes.
        for _tick in range(20):
            client.handle(clock.ticks_ms())
            if client._tx_partial is None and not client._tx_queue:
                break
        assert client._tx_partial is None
        assert not client._tx_queue
        outbound = socket.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.payload == b"hello world"

    def test_send_socket_error_transitions_to_closed(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.send_text("hi")
        socket.raise_on_send = OSError(99, "send dead")
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert client.last_error is not None


class TestInboundData:
    def test_single_text_frame_fires_on_text(self):
        client, socket, clock, _ = _make_client()
        texts = []
        client.on_text = lambda text: texts.append(text)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(_client_frame(OPCODE_TEXT, b"hello"))
        client.handle(clock.ticks_ms())
        assert texts == ["hello"]

    def test_single_binary_frame_fires_on_binary(self):
        client, socket, clock, _ = _make_client()
        data = []
        client.on_binary = lambda payload: data.append(payload)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(_client_frame(OPCODE_BINARY, b"\x00\x01\x02"))
        client.handle(clock.ticks_ms())
        assert data == [b"\x00\x01\x02"]

    def test_large_frame_drains_within_one_tick(self):
        # The recv scratch caps a single recv_into at 512 B, but the
        # drain loops until the 1024 B default recv_budget_per_tick is
        # spent.  A 600 B payload (604 B on the wire, past the 512 B
        # single-read cap) therefore completes and fires on_binary in a
        # single handle() call rather than stalling until the next tick.
        client, socket, clock, _ = _make_client()
        data = []
        client.on_binary = lambda payload: data.append(payload)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        payload = bytes(index & 0xFF for index in range(600))
        socket.feed_inbound(_client_frame(OPCODE_BINARY, payload))
        client.handle(clock.ticks_ms())
        assert data == [payload]

    def test_invalid_utf8_text_closes_with_bad_data(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(_client_frame(OPCODE_TEXT, b"\xff\xfe"))
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSING
        # The CLOSE frame we queued is still in tx_queue.  Verify by draining.
        client.handle(clock.ticks_ms())
        sent = socket.read_outbound()
        parser = FrameParser()
        parser.feed(sent)
        code, _reason = struct.unpack("!H", parser.payload[:2])[0], parser.payload[2:]
        assert code == CLOSE_BAD_DATA

    def test_server_masked_frame_closes_with_protocol_error(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        # Servers MUST NOT mask outbound.  Injecting mask is a violation.
        socket.feed_inbound(encode_frame(OPCODE_TEXT, b"hi", mask=b"mask"))
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSING
        client.handle(clock.ticks_ms())
        sent = socket.read_outbound()
        parser = FrameParser()
        parser.feed(sent)
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_PROTOCOL_ERROR

    def test_protocol_error_in_frame_parse_closes(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        # Reserved opcode 0x3
        socket.feed_inbound(b"\x83\x00")
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSING
        client.handle(clock.ticks_ms())
        sent = socket.read_outbound()
        parser = FrameParser()
        parser.feed(sent)
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_PROTOCOL_ERROR

    def test_peer_eof_post_open_is_protocol_error(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.close_inbound()
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert "without sending a CLOSE frame" in str(client.last_error)


class TestFragmentation:
    def test_text_fragmented_into_two_frames_reassembles(self):
        client, socket, clock, _ = _make_client()
        texts = []
        client.on_text = lambda text: texts.append(text)
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(
            encode_frame(OPCODE_TEXT, b"hel", fin=False, mask=None)
            + encode_frame(OPCODE_CONTINUATION, b"lo!", fin=True, mask=None),
        )
        # Two ticks, one per frame the parser consumes.
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        assert texts == ["hello!"]

    def test_continuation_with_no_in_progress_closes(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(
            encode_frame(OPCODE_CONTINUATION, b"orphan", fin=True, mask=None),
        )
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSING
        client.handle(clock.ticks_ms())
        sent = socket.read_outbound()
        parser = FrameParser()
        parser.feed(sent)
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_PROTOCOL_ERROR

    def test_text_mid_fragmentation_closes(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(
            encode_frame(OPCODE_TEXT, b"part1", fin=False, mask=None)
            + encode_frame(OPCODE_TEXT, b"second", fin=True, mask=None),
        )
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSING

    def test_unbounded_empty_continuation_run_closes(self):
        # A message that never makes byte progress (endless empty
        # continuation frames) must be closed, not spun on forever.
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        frames = encode_frame(OPCODE_TEXT, b"", fin=False, mask=None)
        for _ in range(64):
            frames += encode_frame(OPCODE_CONTINUATION, b"", fin=False, mask=None)
        socket.feed_inbound(frames)
        for _ in range(65):
            client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSING
        client.handle(clock.ticks_ms())
        parser = FrameParser()
        parser.feed(socket.read_outbound())
        code = struct.unpack("!H", parser.payload[:2])[0]
        assert code == CLOSE_PROTOCOL_ERROR
