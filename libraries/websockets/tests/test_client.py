"""Tests for chumicro_websockets.WebSocketClient — slice 2.

Drives the client against an in-memory ``FakeSocket`` (lifted to
``chumicro_websockets.testing.FakeConnection`` in slice 4) so the
state machine, callbacks, fragmentation reassembly, oversize policy,
auto-pong, auto-ping, timeouts, and close handshake are all
exercised without a real TCP/TLS stack.
"""

import struct

from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    CLOSE_BAD_DATA,
    CLOSE_GOING_AWAY,
    CLOSE_INTERNAL_ERROR,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_CONTINUATION,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    WebSocketBackpressureError,
    WebSocketClient,
    WebSocketHandshakeError,
    WebSocketState,
    WebSocketStateError,
    WebSocketTimeoutError,
    WebSocketURLError,
    WhenOversized,
    derive_accept_key,
)
from chumicro_websockets._wire import (
    WS_MAGIC_GUID,
    FrameParser,
    HandshakeRequestParser,
    encode_close_payload,
    encode_frame,
)
from chumicro_websockets.client import ConnectingPhase
from chumicro_websockets.testing import FakeConnection

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


# Backwards-compatible alias kept so the in-test name in this module reads
# naturally — the public testing fake is :class:`FakeConnection`.
FakeSocket = FakeConnection


def _make_factory(socket: FakeConnection, *, expected_use_tls: bool | None = None):
    """Connection-factory closure that records its args + returns *socket*."""
    record = {"calls": []}

    def factory(host, port, use_tls):
        record["calls"].append((host, port, use_tls))
        if expected_use_tls is not None:
            assert use_tls is expected_use_tls
        return socket

    return factory, record


def _drive_handshake(
    client: WebSocketClient,
    socket: FakeSocket,
    clock: FakeTicks,
) -> bytes:
    """Push ticks until SENDING_HANDSHAKE finishes, then craft + feed a 101.

    Returns the request bytes the client wrote so callers can assert on
    them (``Sec-WebSocket-Key`` etc.).  Leaves the client OPEN.
    """
    # Drain handshake send.
    while client.state == WebSocketState.CONNECTING and (
        client._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE
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
        connection_factory=factory,
        ticks=clock,
        **kwargs,
    )
    return client, socket, clock, record


def _client_frame(opcode: int, payload: bytes) -> bytes:
    """Encode a server→client frame (no mask) for inbound feeding."""
    return encode_frame(opcode, payload, fin=True, mask=None)


# ---------------------------------------------------------------------------
# Constructor + properties
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_initial_state_is_connecting(self):
        client, _socket, _clock, _ = _make_client()
        assert client.state == WebSocketState.CONNECTING

    def test_state_url_close_fields_blank_pre_connect(self):
        client, _socket, _clock, _ = _make_client()
        assert client.url == ""
        assert client.last_close_code is None
        assert client.last_close_reason == ""
        assert client.last_error is None

    def test_check_pre_connect_returns_false(self):
        client, _socket, clock, _ = _make_client()
        assert client.check(clock.ticks_ms()) is False

    def test_handle_pre_connect_is_noop(self):
        client, socket, clock, _ = _make_client()
        client.handle(clock.ticks_ms())
        assert socket.read_outbound() == b""


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------


class TestConnect:
    def test_invokes_factory_with_parsed_url(self):
        client, _socket, _clock, record = _make_client()
        client.connect("ws://api.example.com:8080/socket?q=1")
        assert record["calls"] == [("api.example.com", 8080, False)]
        assert client.url == "ws://api.example.com:8080/socket?q=1"

    def test_wss_passes_use_tls_true(self):
        socket = FakeSocket()
        clock = FakeTicks()
        factory, record = _make_factory(socket, expected_use_tls=True)
        client = WebSocketClient(
            connection_factory=factory,
            ticks=clock,
        )
        client.connect("wss://secure.example.com/")
        assert record["calls"] == [("secure.example.com", 443, True)]

    def test_url_must_be_ws_or_wss(self):
        client, _socket, _clock, _ = _make_client()
        with raises(WebSocketURLError):
            client.connect("http://example.com/")

    def test_double_connect_raises(self):
        client, _socket, _clock, _ = _make_client()
        client.connect("ws://example.com/")
        with raises(WebSocketStateError, match="only be called once"):
            client.connect("ws://other.example.com/")

    def test_state_is_connecting_after_connect(self):
        client, _socket, _clock, _ = _make_client()
        client.connect("ws://example.com/")
        assert client.state == WebSocketState.CONNECTING

    def test_check_after_connect_returns_true(self):
        client, _socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        assert client.check(clock.ticks_ms()) is True


# ---------------------------------------------------------------------------
# Opening handshake — send phase
# ---------------------------------------------------------------------------


class TestHandshakeSend:
    def test_handle_pushes_request_bytes(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        client.handle(clock.ticks_ms())
        outbound = socket.peek_outbound()
        assert outbound.startswith(b"GET / HTTP/1.1\r\n")
        assert b"Upgrade: websocket\r\n" in outbound
        assert b"Sec-WebSocket-Version: 13\r\n" in outbound

    def test_send_chunked_completes_across_ticks(self):
        socket = FakeSocket()
        socket.send_chunk_cap = 16  # only 16 bytes per send
        client, _socket, clock, _ = _make_client(socket=socket)
        client.connect("ws://example.com/")
        # Multiple handles needed to drain handshake.
        seen_phases = []
        for _tick in range(40):
            seen_phases.append(client._connecting_phase)
            if client._connecting_phase != ConnectingPhase.SENDING_HANDSHAKE:
                break
            client.handle(clock.ticks_ms())
        assert client._connecting_phase == ConnectingPhase.RECEIVING_HANDSHAKE

    def test_eagain_during_send_keeps_state(self):
        socket = FakeSocket()
        socket.raise_on_send = OSError(11, "would block")
        client, _socket, clock, _ = _make_client(socket=socket)
        client.connect("ws://example.com/")
        client.handle(clock.ticks_ms())
        # State unchanged; no bytes were consumed.
        assert client.state == WebSocketState.CONNECTING
        assert client._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE

    def test_send_error_transitions_to_closed(self):
        socket = FakeSocket()
        socket.raise_on_send = OSError(99, "socket dead")
        client, _socket, clock, _ = _make_client(socket=socket)
        closes = []
        client.on_close = lambda code, reason: closes.append((code, reason))
        client.connect("ws://example.com/")
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert isinstance(client.last_error, WebSocketHandshakeError)
        assert closes == [(CLOSE_INTERNAL_ERROR, str(client.last_error))]


# ---------------------------------------------------------------------------
# Opening handshake — receive phase
# ---------------------------------------------------------------------------


class TestHandshakeReceive:
    def test_valid_response_transitions_to_open(self):
        client, socket, clock, _ = _make_client()
        opens = []
        client.on_open = lambda: opens.append("open")
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        assert client.state == WebSocketState.OPEN
        assert opens == ["open"]

    def test_invalid_status_transitions_to_closed(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        # Drain SEND phase first.
        while client._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE:
            client.handle(clock.ticks_ms())
        socket.read_outbound()
        socket.feed_inbound(
            b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n",
        )
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert isinstance(client.last_error, WebSocketHandshakeError)

    def test_peer_eof_mid_handshake_is_failure(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        while client._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE:
            client.handle(clock.ticks_ms())
        socket.close_inbound()
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert isinstance(client.last_error, WebSocketHandshakeError)
        assert "mid-handshake" in str(client.last_error)

    def test_eagain_during_receive_keeps_state(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        while client._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE:
            client.handle(clock.ticks_ms())
        # No inbound bytes, no EOF — recv_into raises EAGAIN.
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CONNECTING

    def test_leftover_bytes_flow_into_frame_parser(self):
        client, socket, clock, _ = _make_client()
        opens = []
        client.on_open = lambda: opens.append("open")
        texts = []
        client.on_text = lambda text: texts.append(text)
        client.connect("ws://example.com/")
        # Drive handshake send.
        while client._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE:
            client.handle(clock.ticks_ms())
        request = socket.read_outbound()
        parser = HandshakeRequestParser()
        parser.feed(request)
        accept = derive_accept_key(parser.client_key)
        # Piggyback a TEXT frame after the response terminator.
        socket.feed_inbound(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept.encode("ascii") + b"\r\n\r\n"
            + _client_frame(OPCODE_TEXT, b"hello"),
        )
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.OPEN
        assert opens == ["open"]
        assert texts == ["hello"]

    def test_extra_headers_appear_in_request(self):
        client, socket, clock, _ = _make_client()
        client.connect(
            "ws://example.com/",
            extra_headers={"Origin": "https://app.example.com"},
        )
        client.handle(clock.ticks_ms())
        outbound = socket.peek_outbound()
        assert b"Origin: https://app.example.com\r\n" in outbound


# ---------------------------------------------------------------------------
# Handshake timeout
# ---------------------------------------------------------------------------


class TestHandshakeTimeout:
    def test_deadline_elapses(self):
        client, socket, clock, _ = _make_client(handshake_timeout_ms=1000)
        closes = []
        client.on_close = lambda code, reason: closes.append((code, reason))
        client.connect("ws://example.com/")
        # Drain SEND phase, then sit in RECEIVING with no inbound.
        while client._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE:
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


# ---------------------------------------------------------------------------
# send_text / send_binary
# ---------------------------------------------------------------------------


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
        # Outbound is masked client frame; verify by parsing via FrameParser
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
        # Drain over multiple handles; each capped at 4 bytes.
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


# ---------------------------------------------------------------------------
# Inbound text / binary
# ---------------------------------------------------------------------------


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

    def test_invalid_utf8_text_closes_with_bad_data(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.feed_inbound(_client_frame(OPCODE_TEXT, b"\xff\xfe"))
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSING
        # The CLOSE frame we queued is still in tx_queue; verify by draining.
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
        # Servers MUST NOT mask outbound; injecting mask is a violation.
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


# ---------------------------------------------------------------------------
# Inbound fragmentation
# ---------------------------------------------------------------------------


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
        # Two ticks — one per frame the parser consumes.
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


# ---------------------------------------------------------------------------
# Control frames
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Close handshake
# ---------------------------------------------------------------------------


class TestCloseHandshake:
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
        # Echo close was queued; one more handle drains it.
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
        # CLOSE_ABNORMAL (1006) is reserved — encode_close_payload raises.
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


# ---------------------------------------------------------------------------
# Oversized inbound messages
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Auto-ping
# ---------------------------------------------------------------------------


class TestAutoPing:
    def test_auto_ping_fires_after_interval(self):
        client, socket, clock, _ = _make_client(
            ping_interval_ms=1000,
            pong_timeout_ms=5000,
        )
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.read_outbound()
        # Below the interval — no ping.
        clock.advance(500)
        client.handle(clock.ticks_ms())
        assert socket.peek_outbound() == b""
        # Above the interval — ping enqueues this tick, drains the next.
        clock.advance(700)
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        outbound = socket.read_outbound()
        parser = FrameParser()
        parser.feed(outbound)
        assert parser.opcode == OPCODE_PING

    def test_pong_overdue_triggers_close(self):
        client, socket, clock, _ = _make_client(
            ping_interval_ms=1000,
            pong_timeout_ms=2000,
        )
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.read_outbound()
        # First auto-ping.
        clock.advance(1500)
        client.handle(clock.ticks_ms())
        socket.read_outbound()
        # No pong — wait past pong_timeout.
        clock.advance(3000)
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert isinstance(client.last_error, WebSocketTimeoutError)


# ---------------------------------------------------------------------------
# Recv socket errors
# ---------------------------------------------------------------------------


class TestRecvErrors:
    def test_recv_error_transitions_to_closed(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.raise_on_recv = OSError(99, "recv dead")
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert client.last_error is not None

    def test_eagain_during_recv_keeps_open(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        # No inbound bytes; recv_into raises EAGAIN.  Client stays OPEN.
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.OPEN


# ---------------------------------------------------------------------------
# Sec-WebSocket-Accept derivation
# ---------------------------------------------------------------------------


class TestClientEdges:
    """Additional defensive paths and runtime-checked branches."""

    def test_check_returns_false_after_closed(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.close()
        socket.feed_inbound(
            _client_frame(OPCODE_CLOSE, encode_close_payload(CLOSE_NORMAL, "")),
        )
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert client.check(clock.ticks_ms()) is False

    def test_check_returns_true_when_tx_partial_set(self):
        socket = FakeSocket()
        socket.send_chunk_cap = 4
        client, _socket, clock, _ = _make_client(
            socket=socket,
            send_budget_per_tick=4,
        )
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.send_text("hello world")
        # First tick partially sends; client._tx_partial is now non-None.
        client.handle(clock.ticks_ms())
        assert client._tx_partial is not None
        assert client.check(clock.ticks_ms()) is True

    def test_drain_outbound_eagain_keeps_open(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.send_text("hi")
        socket.raise_on_send = OSError(11, "would block")
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.OPEN
        # Frame still queued.
        assert client._tx_queue or client._tx_partial is not None

    def test_drain_outbound_send_returns_zero(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.send_text("hi")
        original_send = socket.send
        socket.send = lambda _data: 0
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.OPEN
        socket.send = original_send

    def test_handshake_send_returns_zero_keeps_state(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        socket.send = lambda _data: 0
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CONNECTING
        assert client._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE


class TestRequestShape:
    def test_request_carries_correct_accept_derivation(self):
        # Verify the request-response coupling: client's key produces the
        # server's accept token via the GUID-suffix SHA-1 base64 derivation.
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        request_bytes = _drive_handshake(client, socket, clock)
        # Parse client's key out of the request.
        parser = HandshakeRequestParser()
        parser.feed(request_bytes)
        # Spec invariant: derive_accept_key == sha1(key + GUID) base64.
        # We don't re-derive here — the handshake already verified
        # the round-trip — but assert the key was a valid base64
        # nonce so future regressions surface here too.
        import binascii
        decoded = binascii.a2b_base64(parser.client_key.encode("ascii"))
        assert len(decoded) == 16
        assert WS_MAGIC_GUID == "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ---------------------------------------------------------------------------
# from_config — config-aware construction
# ---------------------------------------------------------------------------


class TestClientFromConfig:
    """``WebSocketClient.from_config`` reads the client-side keys from
    the ``[tool.chumicro.config]`` manifest with sensible defaults.
    Like ntp's from_config, no key is required — host/port/use_tls
    live on each ``connect()`` URL, not on the client.

    ``websockets.client.connect_url`` is in the manifest because users
    set it per-project, but ``from_config`` doesn't read it (URL is a
    per-connection argument the user passes to ``connect()``)."""

    def test_reads_max_message_bytes_from_config(self) -> None:
        sock = FakeSocket()
        factory = lambda host, port, use_tls: sock  # noqa: ARG005,E731
        client = WebSocketClient.from_config(
            {"websockets.client.max_message_bytes": 4096},
            connection_factory=factory,
        )
        assert client._max_message_bytes == 4096  # noqa: SLF001

    def test_defaults_apply_when_keys_absent(self) -> None:
        """Empty config → max_message_bytes falls back to library default.

        Documents the asymmetry vs ``MQTTClient.from_config``: empty
        config is valid input — no MissingConfigKey is ever raised
        because host/port live on the per-call URL, not on the client.
        """
        from chumicro_websockets._wire import DEFAULT_MAX_MESSAGE_BYTES
        sock = FakeSocket()
        factory = lambda host, port, use_tls: sock  # noqa: ARG005,E731
        client = WebSocketClient.from_config({}, connection_factory=factory)
        assert client._max_message_bytes == DEFAULT_MAX_MESSAGE_BYTES  # noqa: SLF001

    def test_runtime_config_wrapper_works_too(self) -> None:
        """Real ``RuntimeConfig`` instance — same flat-key reads as a dict."""
        from chumicro_config import RuntimeConfig
        sock = FakeSocket()
        factory = lambda host, port, use_tls: sock  # noqa: ARG005,E731
        config = RuntimeConfig(
            {"websockets.client.max_message_bytes": 8192},
        )
        client = WebSocketClient.from_config(config, connection_factory=factory)
        assert client._max_message_bytes == 8192  # noqa: SLF001

    def test_connect_url_not_consumed_by_from_config(self) -> None:
        """``websockets.client.connect_url`` is in the manifest but the
        factory does not read it — URL is a per-connection arg."""
        sock = FakeSocket()
        factory = lambda host, port, use_tls: sock  # noqa: ARG005,E731
        # Build with a connect_url present in config; from_config must
        # not call connect or otherwise act on it.
        client = WebSocketClient.from_config(
            {"websockets.client.connect_url": "ws://ignored.test/"},
            connection_factory=factory,
        )
        assert client.url == ""
        assert not client._connect_called  # noqa: SLF001

    def test_explicit_connection_factory_bypasses_auto_factory(self) -> None:
        """Passing connection_factory= skips the chumicro_sockets wiring."""
        sock = FakeSocket()
        factory = lambda host, port, use_tls: sock  # noqa: ARG005,E731
        client = WebSocketClient.from_config({}, connection_factory=factory)
        assert client._connection_factory is factory  # noqa: SLF001

    def test_non_configlike_input_raises_invalid_config_type(self) -> None:
        """``WebSocketClient.from_config(None)`` /
        ``from_config("not-a-dict")`` / ``from_config(42)`` raise
        :class:`chumicro_config.InvalidConfigType` instead of leaking
        ``AttributeError`` — mirrors the ``load_section`` shape."""
        from chumicro_config import InvalidConfigType

        sock = FakeSocket()
        factory = lambda host, port, use_tls: sock  # noqa: ARG005,E731
        for bad_input in (None, "not-a-dict", 42, ["not", "a", "dict"]):
            with raises(InvalidConfigType):
                WebSocketClient.from_config(bad_input, connection_factory=factory)

    def test_skipped_factory_module_raises_runtime_error(self) -> None:
        """When ``chumicro_websockets.sockets_factory`` is excluded via
        ``__chumicro_skip_factories__``, the default branch of
        ``from_config`` raises ``RuntimeError`` naming the bypass
        kwarg instead of leaking ``ImportError``.  CPython-only —
        sys.modules None-sentinel is CPython-specific; the
        translation behavior itself is runtime-agnostic.
        """
        import sys  # noqa: PLC0415

        from chumicro_test_harness import skip  # noqa: PLC0415

        if sys.implementation.name != "cpython":
            skip("sys.modules None-sentinel is CPython-specific")

        original = sys.modules.get("chumicro_websockets.sockets_factory")
        sys.modules["chumicro_websockets.sockets_factory"] = None
        try:
            try:
                WebSocketClient.from_config({})
            except RuntimeError as exception:
                assert "connection_factory=" in str(exception)
                assert "__chumicro_skip_factories__" in str(exception)
            else:
                raise AssertionError("expected RuntimeError")
        finally:
            if original is None:
                sys.modules.pop("chumicro_websockets.sockets_factory", None)
            else:
                sys.modules["chumicro_websockets.sockets_factory"] = original

    def test_default_factory_threads_radio_and_ssl_context(self) -> None:
        """When no connection_factory is passed, ``from_config`` builds
        one via ``chumicro_websockets.sockets_factory.chumicro_sockets_factory``
        with the radio + ssl_context kwargs threaded through."""
        import chumicro_websockets.sockets_factory as sf

        captured: dict = {}
        sentinel_factory = lambda host, port, use_tls: FakeSocket()  # noqa: ARG005,E731

        def fake_chumicro_sockets_factory(*, radio=None, ssl_context=None):
            captured["radio"] = radio
            captured["ssl_context"] = ssl_context
            return sentinel_factory

        original = sf.chumicro_sockets_factory
        sf.chumicro_sockets_factory = fake_chumicro_sockets_factory
        try:
            client = WebSocketClient.from_config(
                {}, radio="fake-radio", ssl_context="fake-ctx",
            )
        finally:
            sf.chumicro_sockets_factory = original

        assert captured == {"radio": "fake-radio", "ssl_context": "fake-ctx"}
        assert client._connection_factory is sentinel_factory  # noqa: SLF001
