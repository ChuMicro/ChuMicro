"""Runner-shaped WebSocket server built on chumicro-sockets + chumicro-timing.

:class:`WebSocketServer` is the entry point.  Owns a TCP (or TLS)
listening socket handed in at construction time, accepts inbound
connections, dispatches them as :class:`Connection` objects through
the user's ``on_connection`` callback, and drives the per-connection
state machines from its own :meth:`check` / :meth:`handle` runner
contract.

Standalone-port shape only in v1 — sharing a port with
:class:`chumicro_http_server.HttpServer` is a v2 ask (would require
peek-then-route on the HTTP request line).  The optional
*accept_path* knob lets a server filter inbound upgrades by URI
path.

The OPEN/CLOSING/CLOSED machinery — frame dispatch, oversize policy,
control-frame handling, close handshake, send queue, pong watchdog —
lives in :class:`chumicro_websockets._session._BaseSession`, shared
with :class:`chumicro_websockets.client.WebSocketClient`.  This file
owns only the server-specific bits: opening-handshake direction
(parse request → send 101), outbound-mask discipline (servers MUST
NOT mask), and the accept-loop in :class:`WebSocketServer`.
"""

from chumicro_websockets._session import (
    WhenOversized,
    _BaseSession,
    _force_non_blocking,
    _is_eagain,
)
from chumicro_websockets._wire import (
    CLOSE_NORMAL,
    DEFAULT_CLOSE_TIMEOUT_MS,
    DEFAULT_HANDSHAKE_TIMEOUT_MS,
    DEFAULT_MAX_MESSAGE_BYTES,
    DEFAULT_MAX_TX_QUEUE_SIZE,
    DEFAULT_PONG_TIMEOUT_MS,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_SEND_BUDGET_PER_TICK,
    HandshakeParseState,
    HandshakeRequestParser,
    WebSocketHandshakeError,
    WebSocketProtocolError,
    WebSocketState,
    WebSocketStateError,
    encode_server_handshake_response,
    encode_server_rejection,
)

# ---------------------------------------------------------------------------
# Per-connection sub-states (during the opening handshake)
# ---------------------------------------------------------------------------


class ServerHandshakePhase:
    """Sub-states inside CONNECTING — server-side, opposite order from
    the client: read the request first, then write the 101 response.
    """

    READING_REQUEST = "reading_request"
    SENDING_RESPONSE = "sending_response"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


class Connection(_BaseSession):
    """Server-side per-connection state machine + framing pipeline.

    Constructed by :class:`WebSocketServer` once per accepted socket;
    the user wires callbacks via the ``on_connection`` hook.  Server-
    side outbound is never masked (RFC 6455 §5.1).

    Public surface: :meth:`send_text` / :meth:`send_binary` /
    :meth:`send_ping` / :meth:`close`; :attr:`state`,
    :attr:`last_close_code`, :attr:`last_close_reason`,
    :attr:`last_error`, :attr:`request_path`, :attr:`request_headers`
    (set once OPEN); callbacks ``on_text`` / ``on_binary`` /
    ``on_ping`` / ``on_pong`` / ``on_close`` / ``on_oversized``.
    """

    _role_label = "client"  # error messages describe what the *peer* sent
    _inbound_mask_required = True  # clients MUST mask outbound

    def __init__(
        self,
        socket,
        now_ms: int,
        *,
        accept_path: str | None,
        max_message_bytes: int,
        recv_budget_per_tick: int,
        send_budget_per_tick: int,
        max_tx_queue_size: int,
        when_oversized: str,
        pong_timeout_ms: int,
        handshake_timeout_ms: int,
        close_timeout_ms: int,
        ticks,
        on_connection_callback,
    ) -> None:
        _force_non_blocking(socket)
        self._init_session_state(
            socket=socket,
            max_message_bytes=max_message_bytes,
            recv_budget_per_tick=recv_budget_per_tick,
            send_budget_per_tick=send_budget_per_tick,
            max_tx_queue_size=max_tx_queue_size,
            when_oversized=when_oversized,
            pong_timeout_ms=pong_timeout_ms,
            handshake_timeout_ms=handshake_timeout_ms,
            close_timeout_ms=close_timeout_ms,
            ticks=ticks,
        )

        self._accept_path = accept_path
        self._on_connection_callback = on_connection_callback

        self._handshake_phase = ServerHandshakePhase.READING_REQUEST
        self._handshake_request_parser = HandshakeRequestParser()
        self._handshake_deadline_ticks = self._ticks.ticks_add(
            now_ms,
            handshake_timeout_ms,
        )

        self.request_path = ""
        self.request_headers = None

    # ------------------------------------------------------------------
    # Server-driven runner (called by WebSocketServer)
    # ------------------------------------------------------------------

    def check(self, now_ms: int) -> bool:
        """Return ``True`` if there's work to do for this connection."""
        if self.state == WebSocketState.CLOSED:
            return False
        return True

    def handle(self, now_ms: int) -> None:
        """One tick of progress for this connection."""
        if self.state == WebSocketState.CLOSED:
            return

        if self._check_timeouts(now_ms):
            return

        if self.state == WebSocketState.CONNECTING:
            if self._handshake_phase == ServerHandshakePhase.READING_REQUEST:
                self._receive_handshake_chunk(now_ms)
            elif self._handshake_phase == ServerHandshakePhase.SENDING_RESPONSE:
                self._send_handshake_chunk(now_ms)
            return

        # OPEN / CLOSING — drain inbound first, then outbound.
        self._drain_inbound(now_ms)
        self._drain_outbound()

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    def _outbound_mask(self):
        """Servers MUST NOT mask outbound frames (RFC 6455 §5.1)."""
        return None

    def _on_finalized(self) -> None:
        """Clear handshake-deadline state when transitioning to CLOSED."""
        self._handshake_deadline_ticks = None

    # ------------------------------------------------------------------
    # Internal: handshake — server reads first, then sends 101
    # ------------------------------------------------------------------

    def _receive_handshake_chunk(self, now_ms: int) -> None:  # noqa: ARG002 - now_ms reserved for handshake-deadline parity
        chunk = self._recv_chunk(self._recv_budget_per_tick)
        if chunk is None:
            return
        if not chunk:
            self._fail_with_error(
                WebSocketHandshakeError(
                    "client closed connection mid-handshake",
                ),
            )
            return
        try:
            self._handshake_request_parser.feed(chunk)
        except WebSocketHandshakeError as handshake_error:
            self._reject_with_400(str(handshake_error))
            return
        if self._handshake_request_parser.state != HandshakeParseState.DONE:
            return
        # Path filter — reject anything that doesn't match.
        if (
            self._accept_path is not None
            and self._handshake_request_parser.path != self._accept_path
        ):
            self._reject_with_404(
                f"path {self._handshake_request_parser.path!r} not handled",
            )
            return
        # Build 101 response.
        self._handshake_send_buffer = encode_server_handshake_response(
            self._handshake_request_parser.client_key,
        )
        self._handshake_send_offset = 0
        self.request_path = self._handshake_request_parser.path
        self.request_headers = self._handshake_request_parser.headers
        self._post_handshake_carry = self._handshake_request_parser.leftover
        self._handshake_phase = ServerHandshakePhase.SENDING_RESPONSE

    def _on_handshake_send_complete(self, now_ms: int) -> None:
        """101 response fully sent — fire on_connection and enter OPEN."""
        self._enter_open(now_ms)

    def _enter_open(self, now_ms: int) -> None:
        """Transition from sending-response to OPEN; fire user callback."""
        self._handshake_request_parser = None
        self._handshake_send_buffer = None
        self._handshake_phase = None
        self._handshake_deadline_ticks = None
        self.state = WebSocketState.OPEN
        # Hand the connection to the user so they can wire callbacks.
        # Errors from the user callback transition us to CLOSED with
        # CLOSE_INTERNAL_ERROR — the connection isn't viable without
        # the callbacks the user was supposed to install.
        try:
            self._on_connection_callback(self)
        except Exception as callback_error:  # noqa: BLE001 - user code
            self._fail_with_error(
                WebSocketProtocolError(
                    f"on_connection callback raised: {callback_error!r}",
                ),
            )
            return
        # Drain any leftover bytes the request parser carried over —
        # the client may have piggybacked frame bytes after the
        # request terminator.
        if self._post_handshake_carry:
            self._feed_frame_bytes(self._post_handshake_carry, now_ms)
            self._post_handshake_carry = b""

    def _reject_with_400(self, message: str) -> None:
        body = message.encode("utf-8")
        self._send_rejection_response(400, "Bad Request", body)
        self.last_error = WebSocketHandshakeError(message)

    def _reject_with_404(self, message: str) -> None:
        body = message.encode("utf-8")
        self._send_rejection_response(404, "Not Found", body)
        self.last_error = WebSocketHandshakeError(message)

    def _send_rejection_response(
        self,
        status_code: int,
        reason_phrase: str,
        body: bytes,
    ) -> None:
        """Best-effort write of an HTTP rejection + transition to CLOSED."""
        response = encode_server_rejection(status_code, reason_phrase, body=body)
        try:
            self._socket.send(response)
        except Exception:  # noqa: BLE001 - best-effort
            pass
        try:
            self._socket.close()
        except Exception:  # noqa: BLE001 - best-effort
            pass
        self.state = WebSocketState.CLOSED
        self._handshake_deadline_ticks = None
        self.on_close(status_code, reason_phrase)

# ---------------------------------------------------------------------------
# WebSocketServer
# ---------------------------------------------------------------------------


class WebSocketServer:
    """Runner-shaped WebSocket server owning a TCP/TLS listening socket.

    *listener* is typically from
    :func:`chumicro_sockets.tcp_listening_socket` /
    :func:`tls_listening_socket`.  *on_connection* (``callable(connection)``)
    fires once per inbound connection at handshake completion; it
    wires ``connection.on_text`` / ``on_binary`` / ``on_close`` etc.
    before any frames arrive.  Raising from the callback rejects with
    :data:`CLOSE_INTERNAL_ERROR`.  Standalone-port shape only in v1;
    ``accept_path`` filters by URI path with 404 on mismatch.

    For config-driven construction, see :meth:`from_config` —
    one-line factory that builds the listener from
    ``websockets.server.host`` / ``port`` and reads
    ``websockets.server.max_message_bytes`` from
    ``runtime_config.msgpack``.

    Knobs: ``max_connections`` (default 2; inbound accepts past the
    cap close immediately to bound heap + per-tick work);
    ``max_message_bytes`` / ``recv_budget_per_tick`` /
    ``send_budget_per_tick`` / ``max_tx_queue_size`` / ``when_oversized`` /
    ``pong_timeout_ms`` / ``handshake_timeout_ms`` /
    ``close_timeout_ms`` — same semantics as
    :class:`WebSocketClient`, applied per-connection;
    ``ticks`` — optional tick source (any object exposing
    ``ticks_ms`` / ``ticks_diff`` / ``ticks_add``); defaults to
    :mod:`chumicro_timing`'s ``ticks`` submodule.  Tests pass
    ``FakeTicks`` from :mod:`chumicro_timing.testing`.
    """

    @classmethod
    def from_config(
        cls,
        config: object,
        on_connection: object,
        *,
        radio: object | None = None,
        listener: object | None = None,
        accept_path: str | None = None,
        max_connections: int = 2,
    ) -> "WebSocketServer":
        """Build a :class:`WebSocketServer` from runtime config.

        Reads optional ``websockets.server.host`` /
        ``websockets.server.port`` / ``websockets.server.max_message_bytes``
        — empty ``config`` produces a server bound to ``0.0.0.0:8765``.
        *on_connection* is required (wires per-connection callbacks
        before frames arrive).  A *listener* override bypasses the
        auto-built :func:`chumicro_sockets.tcp_listening_socket`.
        *accept_path* + *max_connections* are app-routing knobs not
        in the config manifest.
        """
        if listener is None:
            from chumicro_sockets import tcp_listening_socket  # noqa: PLC0415
            host = config.get("websockets.server.host", "0.0.0.0")
            port = config.get("websockets.server.port", 8765)
            listener = tcp_listening_socket(host, port, radio=radio)
        return cls(
            listener=listener,
            on_connection=on_connection,
            max_connections=max_connections,
            accept_path=accept_path,
            max_message_bytes=config.get(
                "websockets.server.max_message_bytes",
                DEFAULT_MAX_MESSAGE_BYTES,
            ),
        )

    def __init__(
        self,
        listener,
        on_connection,
        *,
        max_connections: int = 2,
        accept_path: str | None = None,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        recv_budget_per_tick: int = DEFAULT_RECV_BUDGET_PER_TICK,
        send_budget_per_tick: int = DEFAULT_SEND_BUDGET_PER_TICK,
        max_tx_queue_size: int = DEFAULT_MAX_TX_QUEUE_SIZE,
        when_oversized: str = WhenOversized.DROP_WITH_EVENT,
        pong_timeout_ms: int = DEFAULT_PONG_TIMEOUT_MS,
        handshake_timeout_ms: int = DEFAULT_HANDSHAKE_TIMEOUT_MS,
        close_timeout_ms: int = DEFAULT_CLOSE_TIMEOUT_MS,
        ticks: object | None = None,
    ) -> None:
        self._listener = listener
        self._on_connection = on_connection
        self._max_connections = max_connections
        self._accept_path = accept_path
        self._max_message_bytes = max_message_bytes
        self._recv_budget_per_tick = recv_budget_per_tick
        self._send_budget_per_tick = send_budget_per_tick
        self._max_tx_queue_size = max_tx_queue_size
        self._when_oversized = when_oversized
        self._pong_timeout_ms = pong_timeout_ms
        self._handshake_timeout_ms = handshake_timeout_ms
        self._close_timeout_ms = close_timeout_ms

        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        self._ticks = ticks

        self._connections: list[Connection] = []
        self.closed = False

    # ------------------------------------------------------------------
    # Public observation
    # ------------------------------------------------------------------

    @property
    def connections(self) -> tuple:
        """Tuple of currently-active :class:`Connection` objects."""
        return tuple(self._connections)

    @property
    def connection_count(self) -> int:
        """How many connections are currently active (any non-CLOSED state)."""
        return len(self._connections)

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Stop accepting new connections + close every active session.
        Per-connection ``on_close`` callbacks fire as they finalize.
        After :meth:`close`, :meth:`check` returns ``False`` and
        :meth:`handle` is a no-op.
        """
        if self.closed:
            return
        try:
            self._listener.close()
        except Exception:  # noqa: BLE001 - best-effort
            pass
        for connection in list(self._connections):
            if connection.state not in (WebSocketState.CLOSED,):
                try:
                    connection.close(CLOSE_NORMAL, "server shutting down")
                except WebSocketStateError:
                    pass
                # Force-finalize so the user's on_close fires even
                # when the close handshake can't complete.
                connection._finalize_closed()
        self._connections.clear()
        self.closed = True

    # ------------------------------------------------------------------
    # Runner contract
    # ------------------------------------------------------------------

    def check(self, now_ms: int) -> bool:
        """Return ``True`` if there's work to do this tick."""
        if self.closed:
            return False
        # Always True — accept loop must run, and any active connection
        # may need attention.  Conservative; cheap enough.
        return True

    def handle(self, now_ms: int) -> None:
        """Accept new connections + advance every active connection one tick."""
        if self.closed:
            return
        self._accept_pending(now_ms)
        # Iterate over a snapshot so a connection finalizing inside
        # handle() can mutate the list without breaking iteration.
        for connection in list(self._connections):
            if connection.state == WebSocketState.CLOSED:
                self._connections.remove(connection)
                continue
            connection.handle(now_ms)
            if connection.state == WebSocketState.CLOSED:
                self._connections.remove(connection)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _accept_pending(self, now_ms: int) -> None:
        """Drain any pending accepts up to the connection cap."""
        while True:
            if len(self._connections) >= self._max_connections:
                return
            try:
                accepted = self._listener.accept()
            except Exception as accept_error:  # noqa: BLE001 - narrow below
                if _is_eagain(accept_error):
                    return
                # Listener errors are fatal-ish; record + close.
                # Caller decides whether to rebuild the listener.
                return
            if accepted is None:
                return
            client_socket, _address = accepted
            connection = Connection(
                client_socket,
                now_ms,
                accept_path=self._accept_path,
                max_message_bytes=self._max_message_bytes,
                recv_budget_per_tick=self._recv_budget_per_tick,
                send_budget_per_tick=self._send_budget_per_tick,
                max_tx_queue_size=self._max_tx_queue_size,
                when_oversized=self._when_oversized,
                pong_timeout_ms=self._pong_timeout_ms,
                handshake_timeout_ms=self._handshake_timeout_ms,
                close_timeout_ms=self._close_timeout_ms,
                ticks=self._ticks,
                on_connection_callback=self._on_connection,
            )
            self._connections.append(connection)
