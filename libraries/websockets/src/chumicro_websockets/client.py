"""Runner-shaped WebSocket client built on chumicro-sockets + chumicro-timing.

:class:`WebSocketClient` is the entry point.  Runner-shaped —
:meth:`check(now_ms) -> bool` reports whether work is pending;
:meth:`handle(now_ms)` performs one tick of progress.  No threads,
no async — cooperative dispatch in the caller's tick loop.  The
canonical promise: an LED can keep blinking on the same board
through the opening handshake, frame I/O, and the close handshake.

Single-connection per client: two parallel websocket sessions need
two :class:`WebSocketClient` instances.  Mirrors
:class:`chumicro_mqtt.MQTTClient`'s "one broker per client" shape.

The OPEN/CLOSING/CLOSED machinery — frame dispatch, oversize policy,
control-frame handling, close handshake, send queue, pong watchdog —
lives in :class:`chumicro_websockets._session._BaseSession`, shared
with :class:`chumicro_websockets.server.Connection`.  This file owns
only the client-specific bits: opening-handshake direction (send
request → parse 101), outbound-mask discipline (clients MUST mask),
and the optional auto-ping keep-alive.
"""

from chumicro_timing import ticks_add, ticks_diff, ticks_ms

from chumicro_websockets._session import (
    WhenOversized,
    _BaseSession,
    _force_non_blocking,
    _is_eagain,
    _new_tx_queue,
    _no_callback,
)
from chumicro_websockets._wire import (
    DEFAULT_CLOSE_TIMEOUT_MS,
    DEFAULT_HANDSHAKE_TIMEOUT_MS,
    DEFAULT_MAX_MESSAGE_BYTES,
    DEFAULT_MAX_TX_QUEUE_SIZE,
    DEFAULT_PONG_TIMEOUT_MS,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_SEND_BUDGET_PER_TICK,
    OPCODE_PING,
    FrameParser,  # noqa: F401 - re-exported for tests via chumicro_websockets._wire
    HandshakeParseState,
    HandshakeResponseParser,
    WebSocketHandshakeError,
    WebSocketState,
    WebSocketStateError,
    WebSocketTimeoutError,
    derive_accept_key,
    encode_client_handshake,
    make_mask_key,
    make_websocket_key,
    parse_ws_url,
)

# Re-exports for back-compat — the public package once exported these
# helpers from the client module.  Slimmed __init__.py (slice C) routes
# advanced consumers through `chumicro_websockets._session` directly,
# but server.py still imports the four helpers from here, and the
# WhenOversized symbol stays at this module path so existing callers
# (`from chumicro_websockets import WhenOversized`) keep working.
__all__ = [
    "ConnectingPhase",
    "WebSocketClient",
    "WhenOversized",
    "_force_non_blocking",
    "_is_eagain",
    "_new_tx_queue",
    "_no_callback",
]


# ---------------------------------------------------------------------------
# Connecting sub-states
# ---------------------------------------------------------------------------


class ConnectingPhase:
    """Sub-states inside CONNECTING — send the upgrade request, then
    receive + validate the 101.  Tells ``handle()`` whether to write
    or read.
    """

    SENDING_HANDSHAKE = "sending_handshake"
    RECEIVING_HANDSHAKE = "receiving_handshake"


# ---------------------------------------------------------------------------
# WebSocketClient
# ---------------------------------------------------------------------------


class WebSocketClient(_BaseSession):
    """Non-blocking RFC 6455 WebSocket client.

    Construct with a *connection_factory* (``callable(host, port,
    use_tls) -> socket`` matching
    :func:`chumicro_sockets.tcp_client_socket` /
    :func:`tls_client_socket`) + user knobs, configure callbacks, then
    call :meth:`connect`.  Drive via :meth:`check` / :meth:`handle`
    from a runner tick or hand-rolled loop.  Callbacks fire from
    :meth:`handle` — never from a thread or interrupt.

    Knobs (all default to the matching ``DEFAULT_*`` constant, mirroring
    chumicro-mqtt + chumicro-requests):

    * ``max_message_bytes`` — cap on assembled inbound message size.
    * ``recv_budget_per_tick`` / ``send_budget_per_tick`` — per-tick
      I/O caps; keeps the LED blinking under big payloads.
    * ``max_tx_queue_size`` — outbound queue bound; overflow raises
      :class:`WebSocketBackpressureError`.
    * ``when_oversized`` — :class:`WhenOversized` policy for inbound
      payloads above ``max_message_bytes``.
    * ``ping_interval_ms`` (``None`` = off — most servers drive their
      own keep-alive) + ``pong_timeout_ms``.
    * ``handshake_timeout_ms`` / ``close_timeout_ms`` — per-phase
      timeouts.
    * ``ticks_ms_func`` / ``ticks_add_func`` / ``ticks_diff_func`` —
      inject fakes for testing; default to :mod:`chumicro_timing`.
    """

    _role_label = "server"  # error messages describe what the *peer* sent
    _inbound_mask_required = False  # servers MUST NOT mask outbound

    def __init__(
        self,
        connection_factory,
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
        ticks_ms_func=ticks_ms,
        ticks_add_func=ticks_add,
        ticks_diff_func=ticks_diff,
    ) -> None:
        # Init shared session state with a None socket — connect() fills it in.
        self._init_session_state(
            socket=None,
            max_message_bytes=max_message_bytes,
            recv_budget_per_tick=recv_budget_per_tick,
            send_budget_per_tick=send_budget_per_tick,
            max_tx_queue_size=max_tx_queue_size,
            when_oversized=when_oversized,
            pong_timeout_ms=pong_timeout_ms,
            close_timeout_ms=close_timeout_ms,
            ticks_ms_func=ticks_ms_func,
            ticks_add_func=ticks_add_func,
            ticks_diff_func=ticks_diff_func,
        )

        self._connection_factory = connection_factory
        self._ping_interval_ms = ping_interval_ms
        self._handshake_timeout_ms = handshake_timeout_ms

        # Set on the first connect() call; before then state stays
        # CONNECTING but with no socket / no parsers — `connect()` is
        # what actually kicks off any I/O.
        self._connect_called = False
        self._connecting_phase = None
        self._url = ""

        self._handshake_response_parser = None
        self._handshake_send_buffer = None
        self._handshake_send_offset = 0

        self._handshake_deadline_ticks = None
        self._next_auto_ping_ticks = None

        self.on_open = _no_callback

    # ------------------------------------------------------------------
    # Public observation
    # ------------------------------------------------------------------

    @property
    def url(self):
        """The URL the client connected to (or ``""`` before :meth:`connect`)."""
        return self._url

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

        Non-blocking modulo the *connection_factory* call (which may
        block briefly through DNS + TCP + TLS — same contract as
        :func:`chumicro_sockets.tcp_client_socket`).  After
        :meth:`connect` returns, the client is in
        :data:`WebSocketState.CONNECTING`; subsequent :meth:`handle`
        ticks finish the upgrade and transition to OPEN.

        *extra_headers* (iterable / ``dict`` / :class:`CaseInsensitiveDict`)
        is useful for ``Cookie`` / ``Authorization`` / ``Origin``.
        Reconnection means a fresh client — calling :meth:`connect` a
        second time raises :class:`WebSocketStateError`.
        """
        if self._connect_called:
            raise WebSocketStateError(
                f"connect() may only be called once per WebSocketClient; "
                f"current state is {self._state}",
            )
        self._connect_called = True
        self._url = url

        scheme, host, port, path = parse_ws_url(url)
        use_tls = scheme == "wss"

        self._socket = self._connection_factory(host, port, use_tls)
        _force_non_blocking(self._socket)

        client_key = make_websocket_key()
        self._handshake_send_buffer = encode_client_handshake(
            host,
            port,
            path,
            client_key,
            extra_headers=extra_headers,
        )
        self._handshake_send_offset = 0
        self._handshake_response_parser = HandshakeResponseParser(
            derive_accept_key(client_key),
        )

        budget_ms = self._handshake_timeout_ms if timeout_ms is None else timeout_ms
        self._handshake_deadline_ticks = self._ticks_add(
            self._ticks_ms(),
            budget_ms,
        )

        self._state = WebSocketState.CONNECTING
        self._connecting_phase = ConnectingPhase.SENDING_HANDSHAKE

    # ------------------------------------------------------------------
    # Runner contract
    # ------------------------------------------------------------------

    def check(self, now_ms: int) -> bool:
        """Return ``True`` if there's work to do on this tick.  Cheap to
        call; safe to invoke before :meth:`connect` (returns ``False``).
        """
        if self._state == WebSocketState.CLOSED:
            return False
        if not self._connect_called:
            return False
        if self._tx_partial is not None:
            return True
        if self._tx_queue:
            return True
        if self._state == WebSocketState.CONNECTING:
            return True
        if self._state == WebSocketState.OPEN:
            return True
        if self._state == WebSocketState.CLOSING:
            return True
        return False  # pragma: no cover - exhaustive

    def handle(self, now_ms: int) -> None:
        """One tick of progress: drain bounded inbound through the
        framing parser, then bounded outbound from the TX queue.  All
        callbacks fire here.  Safe to call when there's no work.
        """
        if self._state == WebSocketState.CLOSED or not self._connect_called:
            return

        # Timeout checks first — even if there's other work to do,
        # an expired handshake / close / pong-overdue overrides.
        if self._check_timeouts(now_ms):
            return

        if self._state == WebSocketState.CONNECTING:
            if self._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE:
                self._send_handshake_chunk()
            elif self._connecting_phase == ConnectingPhase.RECEIVING_HANDSHAKE:
                self._receive_handshake_chunk()
            return

        # OPEN / CLOSING — drain inbound first (peer may have sent
        # CLOSE we need to acknowledge), then outbound, then auto-ping.
        self._drain_inbound()
        self._drain_outbound()

        if self._state == WebSocketState.OPEN:
            self._maybe_emit_auto_ping(now_ms)

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    def _outbound_mask(self):
        """Clients MUST mask outbound frames (RFC 6455 §5.1)."""
        return make_mask_key()

    def _on_finalized(self) -> None:
        """Clear handshake + auto-ping state when transitioning to CLOSED."""
        self._handshake_deadline_ticks = None
        self._next_auto_ping_ticks = None

    # ------------------------------------------------------------------
    # Internal: handshake
    # ------------------------------------------------------------------

    def _send_handshake_chunk(self) -> None:
        """Push as much of the pending handshake bytes as the budget allows."""
        remaining = self._handshake_send_buffer[self._handshake_send_offset:]
        if not remaining:
            self._connecting_phase = ConnectingPhase.RECEIVING_HANDSHAKE
            return
        chunk = remaining[: self._send_budget_per_tick]
        try:
            sent = self._socket.send(chunk)
        except Exception as send_error:  # noqa: BLE001 — narrow below
            if _is_eagain(send_error):
                return
            self._fail_with_error(
                WebSocketHandshakeError(
                    f"socket error during handshake send: {send_error!r}",
                ),
            )
            return
        if sent is None or sent == 0:
            return
        self._handshake_send_offset += sent
        if self._handshake_send_offset >= len(self._handshake_send_buffer):
            self._connecting_phase = ConnectingPhase.RECEIVING_HANDSHAKE

    def _receive_handshake_chunk(self) -> None:
        """Read up to recv_budget bytes and feed the handshake parser."""
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
            self._handshake_send_buffer = None
            self._handshake_response_parser = None
            self._connecting_phase = None
            self._handshake_deadline_ticks = None
            self._state = WebSocketState.OPEN
            self._arm_auto_ping()
            self.on_open()
            # The peer may have piggybacked frame bytes after the
            # handshake terminator — drain whatever the parser
            # carried over before yielding the tick.
            if self._post_handshake_carry:
                self._feed_frame_bytes(self._post_handshake_carry)
                self._post_handshake_carry = b""

    # ------------------------------------------------------------------
    # Internal: timeouts + auto-ping
    # ------------------------------------------------------------------

    def _check_timeouts(self, now_ms: int) -> bool:
        """Trip an expired deadline and return ``True`` if we transitioned."""
        if self._handshake_deadline_ticks is not None:
            if self._ticks_diff(self._handshake_deadline_ticks, now_ms) <= 0:
                self._fail_with_error(
                    WebSocketTimeoutError(
                        f"handshake exceeded {self._handshake_timeout_ms} ms",
                    ),
                )
                return True
        return self._check_close_and_pong_timeouts(now_ms)

    def _arm_auto_ping(self) -> None:
        """Schedule the next auto-ping (if enabled)."""
        if self._ping_interval_ms is None:
            return
        self._next_auto_ping_ticks = self._ticks_add(
            self._ticks_ms(),
            self._ping_interval_ms,
        )

    def _maybe_emit_auto_ping(self, now_ms: int) -> None:
        """Send an auto-ping if the interval has elapsed."""
        if self._next_auto_ping_ticks is None:
            return
        if self._ticks_diff(self._next_auto_ping_ticks, now_ms) > 0:
            return
        self._enqueue_internal_frame(OPCODE_PING, b"")
        self._arm_pong_deadline()
        self._next_auto_ping_ticks = self._ticks_add(
            now_ms,
            self._ping_interval_ms,
        )
