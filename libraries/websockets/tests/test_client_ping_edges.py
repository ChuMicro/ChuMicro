"""WebSocket client tests (chumicro_websockets.client): auto-ping,
recv errors, client edges, request shape, from_config."""

import errno

from _client_helpers import (
    FakeSocket,
    _client_frame,
    _drive_handshake,
    _make_client,
)
from chumicro_websockets import (
    CLOSE_NORMAL,
    OPCODE_CLOSE,
    OPCODE_PING,
    WebSocketClient,
    WebSocketState,
    WebSocketTimeoutError,
)
from chumicro_websockets._wire import (
    WS_MAGIC_GUID,
    FrameParser,
    HandshakeRequestParser,
    encode_close_payload,
)
from chumicro_websockets.client import ConnectingPhase


class TestAutoPing:
    def test_auto_ping_fires_after_interval(self):
        client, socket, clock, _ = _make_client(
            ping_interval_ms=1000,
            pong_timeout_ms=5000,
        )
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        socket.read_outbound()
        # Below the interval: no ping.
        clock.advance(500)
        client.handle(clock.ticks_ms())
        assert socket.peek_outbound() == b""
        # Above the interval: ping enqueues this tick, drains the next.
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
        # No pong; wait past pong_timeout.
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
        # No inbound bytes.  recv_into raises EAGAIN; client stays OPEN.
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
        # First tick partially sends.  client._tx_partial is now non-None.
        client.handle(clock.ticks_ms())
        assert client._tx_partial is not None
        assert client.check(clock.ticks_ms()) is True

    def test_drain_outbound_eagain_keeps_open(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        client.send_text("hi")
        socket.raise_on_send = OSError(errno.EAGAIN, "would block")
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
        # Drive past AWAITING_TRANSPORT (dns_ok + tcp_ok), then the
        # third tick attempts the send and gets sent==0 back.
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
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
        # We don't re-derive here, since the handshake already verified
        # the round-trip, but assert the key was a valid base64
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
            transport_factory=factory,
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
        client = WebSocketClient.from_config({}, transport_factory=factory)
        assert client._max_message_bytes == DEFAULT_MAX_MESSAGE_BYTES  # noqa: SLF001

    def test_runtime_config_wrapper_works_too(self) -> None:
        """Real ``RuntimeConfig`` instance — same flat-key reads as a dict."""
        from chumicro_config import RuntimeConfig
        sock = FakeSocket()
        factory = lambda host, port, use_tls: sock  # noqa: ARG005,E731
        config = RuntimeConfig(
            {"websockets.client.max_message_bytes": 8192},
        )
        client = WebSocketClient.from_config(config, transport_factory=factory)
        assert client._max_message_bytes == 8192  # noqa: SLF001

    def test_connect_url_not_consumed_by_from_config(self) -> None:
        """``websockets.client.connect_url`` is in the manifest but the
        factory does not read it — URL is a per-connection arg."""
        sock = FakeSocket()
        factory = lambda host, port, use_tls: sock  # noqa: ARG005,E731
        # Build with a connect_url present in config.  from_config must
        # not call connect or otherwise act on it.
        client = WebSocketClient.from_config(
            {"websockets.client.connect_url": "ws://ignored.test/"},
            transport_factory=factory,
        )
        assert client.url == ""
        assert not client._connect_called  # noqa: SLF001

    def test_explicit_transport_factory_bypasses_auto_factory(self) -> None:
        """Passing transport_factory= skips the chumicro_sockets wiring."""
        sock = FakeSocket()
        factory = lambda host, port, use_tls: sock  # noqa: ARG005,E731
        client = WebSocketClient.from_config({}, transport_factory=factory)
        assert client._transport_factory is factory  # noqa: SLF001

    def test_skipped_factory_module_raises_runtime_error(self) -> None:
        """When ``chumicro_sockets.sockets_factory`` is excluded via
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

        original = sys.modules.get("chumicro_sockets.sockets_factory")
        sys.modules["chumicro_sockets.sockets_factory"] = None
        try:
            try:
                WebSocketClient.from_config({})
            except RuntimeError as exception:
                assert "transport_factory=" in str(exception)
                assert "__chumicro_skip_factories__" in str(exception)
            else:
                raise AssertionError("expected RuntimeError")
        finally:
            if original is None:
                sys.modules.pop("chumicro_sockets.sockets_factory", None)
            else:
                sys.modules["chumicro_sockets.sockets_factory"] = original

    def test_default_factory_threads_radio_and_ssl_context(self) -> None:
        """When no transport_factory is passed, ``from_config`` builds
        one via ``chumicro_sockets.sockets_factory.connector_factory``
        with the radio + ssl_context kwargs threaded through."""
        import chumicro_sockets.sockets_factory as sf

        captured: dict = {}
        sentinel_factory = lambda host, port, use_tls: FakeSocket()  # noqa: ARG005,E731

        def fake_connector_factory(*, radio=None, ssl_context=None):
            captured["radio"] = radio
            captured["ssl_context"] = ssl_context
            return sentinel_factory

        original = sf.connector_factory
        sf.connector_factory = fake_connector_factory
        try:
            client = WebSocketClient.from_config(
                {}, radio="fake-radio", ssl_context="fake-ctx",
            )
        finally:
            sf.connector_factory = original

        assert captured == {"radio": "fake-radio", "ssl_context": "fake-ctx"}
        assert client._transport_factory is sentinel_factory  # noqa: SLF001
