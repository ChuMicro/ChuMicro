"""WebSocket client tests (chumicro_websockets.client): constructor,
connect, opening-handshake send/receive. Sibling slices: the
other test_client_*.py files; wire-level in test_wire_*.py."""

from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    CLOSE_INTERNAL_ERROR,
    OPCODE_TEXT,
    WebSocketClient,
    WebSocketHandshakeError,
    WebSocketState,
    WebSocketStateError,
    WebSocketURLError,
    derive_accept_key,
)
from chumicro_websockets._wire import (
    HandshakeRequestParser,
    encode_frame,
)
from chumicro_websockets.client import ConnectingPhase
from chumicro_websockets.testing import FakeConnection

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
