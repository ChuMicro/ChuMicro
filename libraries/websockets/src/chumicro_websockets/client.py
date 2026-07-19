"""Runner-shaped WebSocket client built on chumicro-sockets and chumicro-timing.

The public entry point is :class:`WebSocketClient`.
"""

from chumicro_websockets._session import (
    WhenOversized,
    _BaseSession,
    _force_non_blocking,
    _no_callback,
)
from chumicro_websockets._wire import (
    CLOSE_NORMAL,
    DEFAULT_CLOSE_TIMEOUT_MS,
    DEFAULT_HANDSHAKE_TIMEOUT_MS,
    DEFAULT_MAX_INBOUND_QUEUE_SIZE,
    DEFAULT_MAX_MESSAGE_BYTES,
    DEFAULT_MAX_TX_QUEUE_SIZE,
    DEFAULT_PONG_TIMEOUT_MS,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_SEND_BUDGET_PER_TICK,
    OPCODE_PING,
    HandshakeParseState,
    HandshakeResponseParser,
    WebSocketHandshakeError,
    WebSocketState,
    WebSocketStateError,
    derive_accept_key,
    encode_client_handshake,
    make_mask_key,
    make_websocket_key,
    parse_ws_url,
)

__all__ = ["WebSocketClient"]

# Mirror chumicro_runner.IO_READ / IO_WRITE by value; literals avoid a runner dependency.
_IO_READ = 1
_IO_WRITE = 2


class ConnectingPhase:
    """Sub-states inside CONNECTING: send the upgrade request, then read the 101."""

    AWAITING_TRANSPORT = "awaiting_transport"
    SENDING_HANDSHAKE = "sending_handshake"
    RECEIVING_HANDSHAKE = "receiving_handshake"


class WebSocketClient(_BaseSession):
    """Non-blocking RFC 6455 WebSocket client."""

    _peer_label = "server"
    _inbound_mask_required = False  # servers MUST NOT mask outbound (RFC 6455 §5.1)

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        radio: object | None = None,
        ssl_context: object | None = None,
        transport_factory: object | None = None,
    ) -> "WebSocketClient":
        """Build a :class:`WebSocketClient` from runtime config."""
        if transport_factory is None:
            try:
                from chumicro_sockets.sockets_factory import (  # noqa: PLC0415
                    connector_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_sockets.sockets_factory not "
                    "available (excluded via __chumicro_skip_factories__ "
                    "or not on the board); pass transport_factory= "
                    "explicitly.",
                ) from exception
            transport_factory = connector_factory(
                radio=radio, ssl_context=ssl_context,
            )
        return cls(
            transport_factory=transport_factory,
            max_message_bytes=config.get(
                "websockets.client.max_message_bytes",
                DEFAULT_MAX_MESSAGE_BYTES,
            ),
        )

    def __init__(
        self,
        transport_factory,
        *,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        recv_budget_per_tick: int = DEFAULT_RECV_BUDGET_PER_TICK,
        send_budget_per_tick: int = DEFAULT_SEND_BUDGET_PER_TICK,
        max_tx_queue_size: int = DEFAULT_MAX_TX_QUEUE_SIZE,
        when_oversized: str = WhenOversized.DROP_WITH_EVENT,
        ping_interval_ms: int | None = None,
        pong_timeout_ms: int = DEFAULT_PONG_TIMEOUT_MS,
        handshake_timeout_ms: int = DEFAULT_HANDSHAKE_TIMEOUT_MS,
        close_timeout_ms: int = DEFAULT_CLOSE_TIMEOUT_MS,
        max_inbound_queue_size: int = DEFAULT_MAX_INBOUND_QUEUE_SIZE,
        ticks: object | None = None,
    ) -> None:
        """Create a client; each keyword defaults to its ``DEFAULT_*`` constant.

        Args:
            transport_factory: Callable ``(host, port, use_tls) -> connector`` for the transport.
            max_message_bytes: Cap on assembled inbound message size.
            recv_budget_per_tick: Per-tick recv cap that keeps ticks LED-friendly.
            send_budget_per_tick: Per-tick send cap.
            max_tx_queue_size: Outbound queue bound; overflow raises :class:`WebSocketBackpressureError`.
            when_oversized: :class:`WhenOversized` policy for payloads above ``max_message_bytes``.
            ping_interval_ms: Auto-ping interval in ms, or ``None`` to disable.
            pong_timeout_ms: Deadline in ms for a PONG after a PING.
            handshake_timeout_ms: Opening-handshake timeout in ms.
            close_timeout_ms: Close-handshake timeout in ms.
            max_inbound_queue_size: Bound on the ``next_message`` queue.
            ticks: Tick source; defaults to the :mod:`chumicro_timing` ``ticks`` submodule.
        """
        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        # socket is None until connect() fills it in.
        self._init_session_state(
            socket=None,
            max_message_bytes=max_message_bytes,
            recv_budget_per_tick=recv_budget_per_tick,
            send_budget_per_tick=send_budget_per_tick,
            max_tx_queue_size=max_tx_queue_size,
            when_oversized=when_oversized,
            pong_timeout_ms=pong_timeout_ms,
            handshake_timeout_ms=handshake_timeout_ms,
            close_timeout_ms=close_timeout_ms,
            max_inbound_queue_size=max_inbound_queue_size,
            ticks=ticks,
        )

        self._transport_factory = transport_factory
        self._connector = None
        self._ping_interval_ms = ping_interval_ms

        self._connect_called = False
        self._connecting_phase = None
        self.url = ""

        # Captured at connect(), consumed by _on_transport_ready once the socket is live.
        self._pending_handshake_host = None
        self._pending_handshake_port = None
        self._pending_handshake_path = None
        self._pending_handshake_extra_headers = None

        self._handshake_response_parser = None

        self._next_auto_ping_ticks = None

        self.on_open = _no_callback

    def connect(
        self,
        url: str,
        *,
        timeout_ms: int | None = None,
        extra_headers: object | None = None,
    ) -> None:
        """Initiate the opening handshake against *url*.

        Args:
            url: ``ws://`` or ``wss://`` URL to connect to.
            timeout_ms: Handshake timeout override in ms, or ``None`` for the default.
            extra_headers: Extra request headers (iterable, ``dict``, or :class:`CaseInsensitiveDict`).

        Raises:
            WebSocketStateError: :meth:`connect` was already called.
        """
        if self._connect_called:
            raise WebSocketStateError(
                f"connect() may only be called once per WebSocketClient; "
                f"current state is {self.state}",
            )
        self._connect_called = True
        self.url = url

        scheme, host, port, path = parse_ws_url(url)
        use_tls = scheme == "wss"

        self._connector = self._transport_factory(host, port, use_tls)
        # Capture params now; encode the request once the connector hands back a live socket.
        self._pending_handshake_host = host
        self._pending_handshake_port = port
        self._pending_handshake_path = path
        self._pending_handshake_extra_headers = extra_headers

        budget_ms = self._handshake_timeout_ms if timeout_ms is None else timeout_ms
        self._handshake_deadline_ticks = self._ticks.ticks_add(
            self._ticks.ticks_ms(),
            budget_ms,
        )

        self.state = WebSocketState.CONNECTING
        self._connecting_phase = ConnectingPhase.AWAITING_TRANSPORT

    def _on_transport_ready(self, now_ms: int) -> None:  # noqa: ARG002 - hook signature
        self._socket = self._connector.socket
        self._connector = None
        _force_non_blocking(self._socket)

        client_key = make_websocket_key()
        self._handshake_send_buffer = encode_client_handshake(
            self._pending_handshake_host,
            self._pending_handshake_port,
            self._pending_handshake_path,
            client_key,
            extra_headers=self._pending_handshake_extra_headers,
        )
        self._handshake_send_view = memoryview(self._handshake_send_buffer)
        self._handshake_send_offset = 0
        self._handshake_response_parser = HandshakeResponseParser(
            derive_accept_key(client_key),
        )
        self._pending_handshake_host = None
        self._pending_handshake_port = None
        self._pending_handshake_path = None
        self._pending_handshake_extra_headers = None

        self._connecting_phase = ConnectingPhase.SENDING_HANDSHAKE

    def check(self, now_ms: int) -> bool:
        """Return ``True`` if there's work to do on this tick."""
        return self._connect_called and self.state != WebSocketState.CLOSED

    def _connecting_wants_read(self, now_ms) -> bool:
        if self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT:
            if self._connector is None:
                return False
            return bool(self._connector.io_interest(now_ms) & _IO_READ)
        return self._connecting_phase == ConnectingPhase.RECEIVING_HANDSHAKE

    def _connecting_wants_write(self, now_ms) -> bool:
        if self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT:
            if self._connector is None:
                return False
            return bool(self._connector.io_interest(now_ms) & _IO_WRITE)
        return self._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE

    @property
    def io_socket(self):
        """The connector's pollable while ``AWAITING_TRANSPORT``, else the live socket."""
        # Inlined instead of super(): CircuitPython's property/super() descriptor lookup fails here.
        if self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT:
            return self._connector.io_socket if self._connector is not None else None
        if self._socket is None:
            return None
        if self.state == WebSocketState.CLOSED:
            return None
        return self._socket

    def next_deadline(self, now_ms: int) -> int | None:
        """Earliest tick at which ``handle()`` must run on a quiet socket."""
        if (
            self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT
            and self.io_socket is None
        ):
            return now_ms
        # Call the base by class, not super(): CircuitPython's super() is unreliable here.
        return _BaseSession.next_deadline(self, now_ms)

    def handle(self, now_ms: int) -> None:
        """One tick of progress: drain bounded inbound, then bounded outbound."""
        if self.state == WebSocketState.CLOSED or not self._connect_called:
            return

        # Timeouts first: an expired handshake / close / pong overrides other work.
        if self._check_timeouts(now_ms):
            return

        if self.state == WebSocketState.CONNECTING:
            if self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT:
                self._advance_connector(now_ms)
            elif self._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE:
                self._send_handshake_chunk(now_ms)
            elif self._connecting_phase == ConnectingPhase.RECEIVING_HANDSHAKE:
                self._receive_handshake_chunk(now_ms)
            return

        # Drain inbound first: the peer may have sent a CLOSE we must acknowledge.
        self._drain_inbound(now_ms)
        self._drain_outbound()

        if self.state == WebSocketState.OPEN:
            self._maybe_emit_auto_ping(now_ms)

    def _advance_connector(self, now_ms: int) -> None:
        connector = self._connector
        connector.tick(now_ms)
        if connector.state == "ready":
            self._on_transport_ready(now_ms)
            return
        if connector.state == "failed":
            error = connector.last_error
            self._connector = None
            self._fail_with_error(
                WebSocketStateError(f"connector failed: {error}"),
            )

    def _outbound_mask(self):
        # Clients MUST mask outbound frames (RFC 6455 §5.1).
        return make_mask_key()

    def _on_handshake_send_complete(self, now_ms: int) -> None:  # noqa: ARG002 - hook signature
        self._connecting_phase = ConnectingPhase.RECEIVING_HANDSHAKE

    def close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        """Initiate a graceful close, or abort an in-flight connect."""
        if self.state in (WebSocketState.CLOSING, WebSocketState.CLOSED):
            raise WebSocketStateError(
                f"close() not allowed in state {self.state}",
            )
        if self.state == WebSocketState.CONNECTING:
            if self.last_close_code is None:
                self.last_close_code = code
                self.last_close_reason = reason
            try:
                if self._socket is not None:
                    self._socket.close()
            except Exception:  # noqa: BLE001 - best-effort socket teardown
                pass
            self.state = WebSocketState.CLOSED
            self._on_finalized()
            self.on_close(self.last_close_code, self.last_close_reason)
            return
        self._send_close(code, reason, None)

    def _on_finalized(self) -> None:
        self._handshake_deadline_ticks = None
        self._next_auto_ping_ticks = None
        if self._connector is not None:
            # Cancel a still-held connector so its half-open socket doesn't leak the pool.
            try:
                self._connector.cancel()
            except Exception:  # noqa: BLE001 - best-effort connector teardown
                pass
            self._connector = None
        self._connecting_phase = None

    def _receive_handshake_chunk(self, now_ms: int) -> None:
        chunk = self._recv_chunk(self._recv_budget_per_tick)
        if chunk is None:
            return
        if not chunk:
            self._fail_with_error(
                WebSocketHandshakeError(
                    "peer closed connection mid-handshake",
                ),
            )
            return
        try:
            self._handshake_response_parser.feed(chunk)
        except WebSocketHandshakeError as handshake_error:
            self._fail_with_error(handshake_error)
            return
        if self._handshake_response_parser.state == HandshakeParseState.DONE:
            self._post_handshake_carry = self._handshake_response_parser.leftover
            self._handshake_send_view = None
            self._handshake_send_buffer = None
            self._handshake_response_parser = None
            self._connecting_phase = None
            self._handshake_deadline_ticks = None
            self.state = WebSocketState.OPEN
            self._arm_auto_ping(now_ms)
            self.on_open()
            # The peer may have piggybacked frame bytes after the handshake; drain the carry.
            if self._post_handshake_carry:
                self._feed_frame_bytes(self._post_handshake_carry, now_ms)
                self._post_handshake_carry = b""

    def _arm_auto_ping(self, now_ms: int) -> None:
        if self._ping_interval_ms is None:
            return
        self._next_auto_ping_ticks = self._ticks.ticks_add(
            now_ms,
            self._ping_interval_ms,
        )

    def _maybe_emit_auto_ping(self, now_ms: int) -> None:
        if self._next_auto_ping_ticks is None:
            return
        if self._ticks.ticks_diff(self._next_auto_ping_ticks, now_ms) > 0:
            return
        self._enqueue_internal_frame(OPCODE_PING, b"")
        self._arm_pong_deadline(now_ms)
        self._next_auto_ping_ticks = self._ticks.ticks_add(
            now_ms,
            self._ping_interval_ms,
        )
