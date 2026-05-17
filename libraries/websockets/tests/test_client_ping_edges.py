"""WebSocket client tests (chumicro_websockets.client): auto-ping,
recv errors, client edges, request shape, from_config."""

from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    CLOSE_NORMAL,
    OPCODE_CLOSE,
    OPCODE_PING,
    WebSocketClient,
    WebSocketState,
    WebSocketTimeoutError,
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
