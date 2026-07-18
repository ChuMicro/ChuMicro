"""Runner-shaped WebSocket client built on chumicro-sockets and chumicro-timing.

:class:`WebSocketClient` is the entry point: :meth:`check` reports
whether work is pending and :meth:`handle` performs one tick of
progress, so an LED can keep blinking through the handshake, frame
I/O, and close. One connection per client.
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

# Poll-interest bits for io_interest, mirroring chumicro_runner.IO_READ /
# IO_WRITE by value; kept as literals to avoid a dependency on the runner.
_IO_READ = 1
_IO_WRITE = 2


# ---------------------------------------------------------------------------
# Connecting sub-states
# ---------------------------------------------------------------------------


class ConnectingPhase:
    """Sub-states inside CONNECTING: send the upgrade request, then
    receive + validate the 101.  Tells ``handle()`` whether to write
    or read.
    """

    AWAITING_TRANSPORT = "awaiting_transport"
    SENDING_HANDSHAKE = "sending_handshake"
    RECEIVING_HANDSHAKE = "receiving_handshake"


# ---------------------------------------------------------------------------
# WebSocketClient
# ---------------------------------------------------------------------------


class WebSocketClient(_BaseSession):
    """Non-blocking RFC 6455 WebSocket client.

    Construct with a *transport_factory*: a ``(host, port, use_tls) ->
    connector`` callable returning a tick-driven non-blocking connector
    (``chumicro_sockets``-based factories work, or anything of the same
    shape). Configure callbacks, call :meth:`connect`, then drive with
    :meth:`check` / :meth:`handle` from a runner tick or your own loop;
    callbacks fire from :meth:`handle`, never from a thread or interrupt.
    See :meth:`from_config` for config-driven construction.

    Knobs (each defaults to the matching ``DEFAULT_*`` constant):

    * ``max_message_bytes``: cap on assembled inbound message size.
    * ``recv_budget_per_tick`` / ``send_budget_per_tick``: per-tick I/O
      caps that keep the LED blinking under big payloads.
    * ``max_tx_queue_size``: outbound queue bound; overflow raises
      :class:`WebSocketBackpressureError`.
    * ``when_oversized``: :class:`WhenOversized` policy for inbound
      payloads above ``max_message_bytes``.
    * ``ping_interval_ms`` (``None`` = off) and ``pong_timeout_ms``.
    * ``handshake_timeout_ms`` / ``close_timeout_ms``: per-phase timeouts.
    * ``ticks``: optional tick source; defaults to the
      :mod:`chumicro_timing` ``ticks`` submodule.
    """

    _peer_label = "server"  # label names the peer in error messages
    _inbound_mask_required = False  # servers MUST NOT mask outbound

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        radio: object | None = None,
        ssl_context: object | None = None,
        transport_factory: object | None = None,
    ) -> "WebSocketClient":
        """Build a :class:`WebSocketClient` from runtime config.

        Reads optional ``websockets.client.max_message_bytes``; no key is
        required, since host / port / TLS come from each :meth:`connect`
        URL. A *transport_factory* override bypasses the auto-built factory.
        """
        if transport_factory is None:
            try:
                from chumicro_websockets.sockets_factory import (  # noqa: PLC0415
                    chumicro_sockets_connector_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_websockets.sockets_factory not "
                    "available (excluded via __chumicro_skip_factories__ "
                    "or not on the board); pass transport_factory= "
                    "explicitly.",
                ) from exception
            transport_factory = chumicro_sockets_connector_factory(
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
        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        # Init shared session state with a None socket.  connect() fills it in.
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

        # Set on the first connect() call; before then there is no socket
        # or parser and no I/O happens.
        self._connect_called = False
        self._connecting_phase = None
        self.url = ""

        # Handshake parameters captured at connect() and consumed by
        # _on_transport_ready once the connector promotes the socket.
        self._pending_handshake_host = None
        self._pending_handshake_port = None
        self._pending_handshake_path = None
        self._pending_handshake_extra_headers = None

        self._handshake_response_parser = None

        self._next_auto_ping_ticks = None

        self.on_open = _no_callback

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def connect(
        self,
        url: str,
        *,
        timeout_ms: int | None = None,
        extra_headers: object | None = None,
    ) -> None:
        """Initiate the opening handshake against *url*.

        Returns immediately after arming the connector, with no network
        I/O on the caller's thread; later :meth:`handle` ticks drive DNS,
        TCP, TLS, and the upgrade exchange. *extra_headers* (iterable,
        ``dict``, or :class:`CaseInsensitiveDict`) is useful for ``Cookie``
        / ``Authorization`` / ``Origin``. Calling :meth:`connect` a second
        time raises :class:`WebSocketStateError`; reconnection means a
        fresh client.
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
        # Capture the parameters now; encode the request only once the
        # connector hands back a live socket.
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
        # Release the captured parameters now that they've been consumed.
        self._pending_handshake_host = None
        self._pending_handshake_port = None
        self._pending_handshake_path = None
        self._pending_handshake_extra_headers = None

        self._connecting_phase = ConnectingPhase.SENDING_HANDSHAKE

    # ------------------------------------------------------------------
    # Runner contract
    # ------------------------------------------------------------------

    def check(self, now_ms: int) -> bool:
        """Return ``True`` if there's work to do on this tick.  Cheap to
        call; safe to invoke before :meth:`connect` (returns ``False``).
        """
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
        """The connector's pollable while ``AWAITING_TRANSPORT``, otherwise
        the live session's socket (``None`` when CLOSED).
        """
        # Base behaviour is inlined rather than via super() because
        # CircuitPython's property/super() descriptor lookup fails here.
        if self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT:
            return self._connector.io_socket if self._connector is not None else None
        if self._socket is None:
            return None
        if self.state == WebSocketState.CLOSED:
            return None
        return self._socket

    def next_deadline(self, now_ms: int) -> int | None:
        """Earliest tick at which ``handle()`` must run on a quiet socket.

        While ``AWAITING_TRANSPORT`` with no pollable yet (the connector is
        still resolving DNS), returns *now_ms* so the loop keeps ticking
        the connector forward instead of sleeping to the far handshake
        deadline. Otherwise the shared handshake / close / pong / auto-ping
        deadlines apply.
        """
        if (
            self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT
            and self.io_socket is None
        ):
            return now_ms
        # Call the base by class, not super(): CircuitPython's super()
        # descriptor lookup is unreliable here (see io_socket).
        return _BaseSession.next_deadline(self, now_ms)

    def handle(self, now_ms: int) -> None:
        """One tick of progress: drain bounded inbound through the
        framing parser, then bounded outbound from the TX queue.  All
        callbacks fire here.  Safe to call when there's no work.
        """
        if self.state == WebSocketState.CLOSED or not self._connect_called:
            return

        # Timeout checks first.  Even if there's other work to do,
        # an expired handshake / close / pong-overdue overrides.
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

        # OPEN / CLOSING: drain inbound first (peer may have sent
        # CLOSE we need to acknowledge), then outbound, then auto-ping.
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

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    def _outbound_mask(self):
        # Clients MUST mask outbound frames (RFC 6455 §5.1).
        return make_mask_key()

    def _on_handshake_send_complete(self, now_ms: int) -> None:  # noqa: ARG002 - hook signature
        self._connecting_phase = ConnectingPhase.RECEIVING_HANDSHAKE

    def close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        """Initiate a graceful close, or abort an in-flight connect.

        While CONNECTING there is no open socket to run a CLOSE handshake
        over, so this finalizes directly instead of queueing a CLOSE frame.
        """
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
            # Cancel a still-held connector so its half-open socket closes
            # instead of leaking on boards with a fixed socket pool.
            try:
                self._connector.cancel()
            except Exception:  # noqa: BLE001 - best-effort connector teardown
                pass
            self._connector = None
        self._connecting_phase = None

    # ------------------------------------------------------------------
    # Internal: handshake
    # ------------------------------------------------------------------

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
            # The peer may have piggybacked frame bytes after the handshake
            # terminator; drain whatever the parser carried over.
            if self._post_handshake_carry:
                self._feed_frame_bytes(self._post_handshake_carry, now_ms)
                self._post_handshake_carry = b""

    # ------------------------------------------------------------------
    # Internal: timeouts + auto-ping
    # ------------------------------------------------------------------

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
