"""Runner-shaped WebSocket client built on chumicro-sockets + chumicro-timing.

:class:`WebSocketClient` is the entry point.  Runner-shaped:
:meth:`check(now_ms) -> bool` reports whether work is pending, and
:meth:`handle(now_ms)` performs one tick of progress.  No threads,
no async; cooperative dispatch in the caller's tick loop, so an
LED can keep blinking on the same board through the opening
handshake, frame I/O, and the close handshake.

Single-connection per client: two parallel websocket sessions need
two :class:`WebSocketClient` instances.

Everything from OPEN onward is shared with
:class:`chumicro_websockets.server.Connection` through
:class:`chumicro_websockets._session._BaseSession`.  This file owns
the client-specific bits: the opening-handshake direction (send
request, parse 101), outbound-mask discipline (clients MUST mask),
and the optional auto-ping keep-alive.
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

# Poll-interest bits for ``io_interest``; mirror ``chumicro_runner.IO_READ``
# / ``IO_WRITE`` by value.  Held as literals rather than imported so the
# stack takes no dependency edge on the runner (bring-your-own-scheduler).
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

    Construct with a *connector_factory*: a ``(host: str, port: int,
    use_tls: bool) -> connector`` callable that hands back a tick-driven
    non-blocking connect state machine.  The connector is a duck-typed
    object exposing ``state`` / ``socket`` / ``last_error`` attributes,
    ``tick(now_ms)`` / ``cancel()`` methods, and the runner-poll
    surface ``io_socket`` / ``io_interest(now_ms)`` /
    ``next_deadline(now_ms)``.  Once the connector reports ``ready``,
    the promoted socket must expose the four-method TCP contract
    (``recv_into`` / ``send`` / ``close`` / ``setblocking``; full shape
    documented on the *connector_factory* parameter below).
    ``chumicro_sockets``-based factories work; so does anything else of
    the same shape.  Configure callbacks, then call :meth:`connect`.
    Drive via :meth:`check` / :meth:`handle` from a runner tick or
    hand-rolled loop.  Callbacks fire from :meth:`handle`, never from a
    thread or interrupt.

    For config-driven construction, see :meth:`from_config`: a
    one-line factory that reads ``websockets.client.max_message_bytes``
    from ``runtime_config.msgpack``.

    Knobs (all default to the matching ``DEFAULT_*`` constant):

    * ``max_message_bytes``: cap on assembled inbound message size.
    * ``recv_budget_per_tick`` / ``send_budget_per_tick``: per-tick
      I/O caps that keep the LED blinking under big payloads.
    * ``max_tx_queue_size``: outbound queue bound; overflow raises
      :class:`WebSocketBackpressureError`.
    * ``when_oversized``: :class:`WhenOversized` policy for inbound
      payloads above ``max_message_bytes``.
    * ``ping_interval_ms`` (``None`` = off; most servers drive their
      own keep-alive) + ``pong_timeout_ms``.
    * ``handshake_timeout_ms`` / ``close_timeout_ms``: per-phase
      timeouts.
    * ``ticks``: optional tick source (any object exposing
      ``ticks_ms`` / ``ticks_diff`` / ``ticks_add``); defaults to the
      :mod:`chumicro_timing` ``ticks`` submodule.  Tests pass
      ``FakeTicks`` from :mod:`chumicro_timing.testing`.
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
        connector_factory: object | None = None,
    ) -> "WebSocketClient":
        """Build a :class:`WebSocketClient` from runtime config.

        Reads optional ``websockets.client.max_message_bytes``.  No
        key is required — host / port / use_tls live on each
        :meth:`connect` URL, not on the client.  A *connector_factory*
        override bypasses the auto-built factory entirely.
        ``websockets.client.connect_url`` is declared in the manifest
        but consumed by your app on the :meth:`connect` call, not by
        ``from_config``.
        """
        if connector_factory is None:
            try:
                from chumicro_websockets.sockets_factory import (  # noqa: PLC0415
                    chumicro_sockets_connector_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_websockets.sockets_factory not "
                    "available (excluded via __chumicro_skip_factories__ "
                    "or not on the board) — pass connector_factory= "
                    "explicitly.",
                ) from exception
            connector_factory = chumicro_sockets_connector_factory(
                radio=radio, ssl_context=ssl_context,
            )
        return cls(
            connector_factory=connector_factory,
            max_message_bytes=config.get(
                "websockets.client.max_message_bytes",
                DEFAULT_MAX_MESSAGE_BYTES,
            ),
        )

    def __init__(
        self,
        connector_factory,
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

        self._connector_factory = connector_factory
        self._connector = None
        self._ping_interval_ms = ping_interval_ms

        # Set on the first connect() call.  Before then state stays
        # CONNECTING but with no socket / no parsers; `connect()` is
        # what actually kicks off any I/O.
        self._connect_called = False
        self._connecting_phase = None
        self.url = ""

        # Handshake parameters captured at :meth:`connect` time and
        # consumed by :meth:`_on_transport_ready` once the connector
        # promotes the socket.  Held as separate attributes (vs a
        # tuple / dataclass) because the four-attribute count beats
        # one allocation on the import-time RAM ledger.
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

        Returns immediately after arming the connector — no network
        I/O on the caller's thread.  After :meth:`connect` returns,
        the client is in :data:`WebSocketState.CONNECTING` with the
        AWAITING_TRANSPORT phase, and subsequent :meth:`handle` ticks
        drive DNS / TCP / TLS via the connector.  Once the connector
        reaches ``ready``, the client transitions to SENDING_HANDSHAKE
        and the WebSocket upgrade exchange begins.

        *extra_headers* (iterable / ``dict`` / :class:`CaseInsensitiveDict`)
        is useful for ``Cookie`` / ``Authorization`` / ``Origin``.
        Reconnection means a fresh client.  Calling :meth:`connect` a
        second time raises :class:`WebSocketStateError`.
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

        self._connector = self._connector_factory(host, port, use_tls)
        # Capture the handshake parameters now; the actual encoding
        # happens once the connector hands back a live socket so the
        # send buffer doesn't sit around mutated-but-unsent for the
        # duration of the connect.
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
        """Promote the connector's socket and encode the upgrade request.

        Called when the connector reaches ``ready``.  Encodes the HTTP
        upgrade request now (deferred from :meth:`connect`), arms the
        response parser, and transitions to SENDING_HANDSHAKE.
        """
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
        """The client reads during the second handshake leg (waiting on
        the server's HTTP 101 response) and during AWAITING_TRANSPORT
        forwards the connector's read interest (TLS handshake rounds
        that consume inbound bytes)."""
        if self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT:
            if self._connector is None:
                return False
            return bool(self._connector.io_interest(now_ms) & _IO_READ)
        return self._connecting_phase == ConnectingPhase.RECEIVING_HANDSHAKE

    def _connecting_wants_write(self, now_ms) -> bool:
        """The client writes during the first handshake leg (sending the
        upgrade request bytes) and during AWAITING_TRANSPORT forwards
        the connector's write interest (TCP-connect / TLS-handshake
        phases that need writability)."""
        if self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT:
            if self._connector is None:
                return False
            return bool(self._connector.io_interest(now_ms) & _IO_WRITE)
        return self._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE

    @property
    def io_socket(self):
        """During AWAITING_TRANSPORT, forward to the in-flight connector
        so ``Runner.wait`` parks on the right pollable; otherwise return
        the live session's socket-ish object as-is (or ``None`` when
        CLOSED).  The runner unwraps any ``.sock`` adapter wrapper at the
        poller.

        Base-class behaviour is inlined here rather than chained via
        ``super().io_socket`` because CircuitPython's property /
        super() descriptor interaction raises ``AttributeError`` on
        the base attribute lookup at runtime.
        """
        if self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT:
            return self._connector.io_socket if self._connector is not None else None
        if self._socket is None:
            return None
        if self.state == WebSocketState.CLOSED:
            return None
        return self._socket

    def next_deadline(self, now_ms: int) -> int | None:
        """Earliest tick at which ``handle()`` must run on a quiet socket.

        While ``AWAITING_TRANSPORT`` with no pollable yet (the connector
        is still resolving DNS, so ``io_socket`` is ``None`` and
        ``Runner.wait`` has nothing to park on), this returns *now_ms* —
        an immediate deadline that keeps the loop ticking the
        tick-driven connector forward instead of sleeping toward the far
        handshake-timeout deadline.  Once a pollable exists (TCP-connect
        onward) or the connect phase ends, the shared handshake / close /
        pong / auto-ping deadlines govern again.

        Calls the base method by class rather than ``super()`` for the
        same reason :attr:`io_socket` inlines: CircuitPython's
        descriptor lookup through ``super()`` is unreliable here.
        """
        if (
            self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT
            and self.io_socket is None
        ):
            return now_ms
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
        """Tick the in-flight connector one phase.

        On ``ready`` promotes the socket via :meth:`_on_transport_ready`
        — the next handle() tick picks up at SENDING_HANDSHAKE.  On
        ``failed`` closes the session via :meth:`_fail_with_error` with
        the connector's error wrapped in
        :class:`WebSocketStateError`.
        """
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
        """Clients MUST mask outbound frames (RFC 6455 §5.1)."""
        return make_mask_key()

    def _on_handshake_send_complete(self, now_ms: int) -> None:  # noqa: ARG002 - hook signature
        """Move from sending the upgrade request to reading the 101 response."""
        self._connecting_phase = ConnectingPhase.RECEIVING_HANDSHAKE

    def close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        """Initiate a graceful close, or abort an in-flight connect.

        While CONNECTING there is no open WebSocket to run the CLOSE
        handshake over, so a queued CLOSE frame could never be sent and
        the next ``handle()`` would touch a ``None`` socket.  Instead
        finalize directly: close any half-open handshake socket and let
        :meth:`_on_finalized` cancel the in-flight connector.
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
        """Clear handshake + auto-ping state and cancel an in-flight connector.

        A connect that fails or is aborted before the transport is ready
        (handshake timeout, ``close()`` during AWAITING_TRANSPORT) still
        holds the connector, whose half-open socket the connector owns —
        cancel it so the socket closes instead of leaking on ports with a
        fixed socket pool, and clear the phase so ``io_socket`` reports
        ``None`` once CLOSED.
        """
        self._handshake_deadline_ticks = None
        self._next_auto_ping_ticks = None
        if self._connector is not None:
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
            self._handshake_send_view = None
            self._handshake_send_buffer = None
            self._handshake_response_parser = None
            self._connecting_phase = None
            self._handshake_deadline_ticks = None
            self.state = WebSocketState.OPEN
            self._arm_auto_ping(now_ms)
            self.on_open()
            # The peer may have piggybacked frame bytes after the
            # handshake terminator.  Drain whatever the parser
            # carried over before yielding the tick.
            if self._post_handshake_carry:
                self._feed_frame_bytes(self._post_handshake_carry, now_ms)
                self._post_handshake_carry = b""

    # ------------------------------------------------------------------
    # Internal: timeouts + auto-ping
    # ------------------------------------------------------------------

    def _arm_auto_ping(self, now_ms: int) -> None:
        """Schedule the next auto-ping (if enabled).

        *now_ms* must be the runner-supplied tick value.  Every caller
        is inside the ``handle()`` path, so we never refetch.
        """
        if self._ping_interval_ms is None:
            return
        self._next_auto_ping_ticks = self._ticks.ticks_add(
            now_ms,
            self._ping_interval_ms,
        )

    def _maybe_emit_auto_ping(self, now_ms: int) -> None:
        """Send an auto-ping if the interval has elapsed."""
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
