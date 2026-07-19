"""Runner-shaped WebSocket server built on chumicro-sockets and chumicro-timing.

The public entry points are :class:`WebSocketServer` and :class:`Connection`.
"""

import errno

from chumicro_websockets._session import (
    WhenOversized,
    _BaseSession,
    _force_non_blocking,
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
    HandshakeParseState,
    HandshakeRequestParser,
    WebSocketHandshakeError,
    WebSocketProtocolError,
    WebSocketState,
    WebSocketStateError,
    encode_server_handshake_response,
    encode_server_rejection,
)


class ServerHandshakePhase:
    """Sub-states inside CONNECTING: read the request, then write the 101 response."""

    READING_REQUEST = "reading_request"
    SENDING_RESPONSE = "sending_response"


class Connection(_BaseSession):
    """Server-side per-connection state machine and framing pipeline."""

    _peer_label = "client"
    _inbound_mask_required = True  # clients MUST mask outbound (RFC 6455 §5.1)

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
        max_inbound_queue_size: int = DEFAULT_MAX_INBOUND_QUEUE_SIZE,
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
            max_inbound_queue_size=max_inbound_queue_size,
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

    def check(self, now_ms: int) -> bool:  # noqa: ARG002 - runner contract
        """Return ``True`` if there's work to do for this connection."""
        return self.state != WebSocketState.CLOSED

    def _connecting_wants_read(self, now_ms) -> bool:  # noqa: ARG002 - runner contract
        return self._handshake_phase == ServerHandshakePhase.READING_REQUEST

    def _connecting_wants_write(self, now_ms) -> bool:  # noqa: ARG002 - runner contract
        return self._handshake_phase == ServerHandshakePhase.SENDING_RESPONSE

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

        # Drain inbound first: the peer may have sent a CLOSE we must acknowledge.
        self._drain_inbound(now_ms)
        self._drain_outbound()

    def _outbound_mask(self):
        # Servers MUST NOT mask outbound frames (RFC 6455 §5.1).
        return None

    def _on_finalized(self) -> None:
        self._handshake_deadline_ticks = None

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
        if (
            self._accept_path is not None
            and self._handshake_request_parser.path != self._accept_path
        ):
            self._reject_with_404(
                f"path {self._handshake_request_parser.path!r} not handled",
            )
            return
        self._handshake_send_buffer = encode_server_handshake_response(
            self._handshake_request_parser.client_key,
        )
        self._handshake_send_view = memoryview(self._handshake_send_buffer)
        self._handshake_send_offset = 0
        self.request_path = self._handshake_request_parser.path
        self.request_headers = self._handshake_request_parser.headers
        self._post_handshake_carry = self._handshake_request_parser.leftover
        self._handshake_phase = ServerHandshakePhase.SENDING_RESPONSE

    def _on_handshake_send_complete(self, now_ms: int) -> None:
        self._enter_open(now_ms)

    def _enter_open(self, now_ms: int) -> None:
        self._handshake_request_parser = None
        self._handshake_send_view = None
        self._handshake_send_buffer = None
        self._handshake_phase = None
        self._handshake_deadline_ticks = None
        self.state = WebSocketState.OPEN
        # Hand off to the user's callback; a raising callback closes us with CLOSE_INTERNAL_ERROR.
        try:
            self._on_connection_callback(self)
        except Exception as callback_error:  # noqa: BLE001 - user code
            self._fail_with_error(
                WebSocketProtocolError(
                    f"on_connection callback raised: {callback_error!r}",
                ),
            )
            return
        # The client may have piggybacked frame bytes after the request; drain the carry.
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


class WebSocketServer:
    """Runner-shaped WebSocket server owning a TCP/TLS listening socket."""

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
        """Build a :class:`WebSocketServer` from runtime config."""
        if listener is None:
            # Lazy import so a client-only deploy never pulls chumicro_sockets onto the board.
            try:
                from chumicro_sockets.sockets_factory import (  # noqa: PLC0415 - lazy
                    listener_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_sockets.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or not on "
                    "the board); pass listener= explicitly.",
                ) from exception
            listener = listener_factory(
                config.get("websockets.server.host", "0.0.0.0"),
                config.get("websockets.server.port", 8765),
                radio=radio,
            )()
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
        max_inbound_queue_size: int = DEFAULT_MAX_INBOUND_QUEUE_SIZE,
        ticks: object | None = None,
    ) -> None:
        """Create a server; each per-connection knob defaults to its ``DEFAULT_*`` constant.

        Args:
            listener: Listening socket, typically from :func:`chumicro_sockets.listener`.
            on_connection: ``callable(connection)`` fired once per connection at handshake completion.
            max_connections: Concurrent-connection cap; at the cap the server stops calling ``accept()``.
            accept_path: URI path to require, or ``None`` to accept any; a mismatch gets a 404.
            max_message_bytes: Per-connection cap on assembled inbound message size.
            recv_budget_per_tick: Per-tick recv cap.
            send_budget_per_tick: Per-tick send cap.
            max_tx_queue_size: Per-connection outbound queue bound.
            when_oversized: :class:`WhenOversized` policy for oversized inbound payloads.
            pong_timeout_ms: Deadline in ms for a PONG after a PING.
            handshake_timeout_ms: Opening-handshake timeout in ms.
            close_timeout_ms: Close-handshake timeout in ms.
            max_inbound_queue_size: Bound on each connection's ``next_message`` queue.
            ticks: Tick source; defaults to the :mod:`chumicro_timing` ``ticks`` submodule.
        """
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
        self._max_inbound_queue_size = max_inbound_queue_size

        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        self._ticks = ticks

        self._connections: list[Connection] = []
        self.closed = False
        #: Most recent non-EAGAIN ``listener.accept()`` failure, or ``None`` if healthy.
        self.last_error: BaseException | None = None

    @property
    def connections(self) -> tuple:
        """Tuple of currently-active :class:`Connection` objects."""
        return tuple(self._connections)

    @property
    def connection_count(self) -> int:
        """How many connections are currently active (any non-CLOSED state)."""
        return len(self._connections)

    def close(self) -> None:
        """Stop accepting new connections and close every active session."""
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
                # Force-finalize so on_close fires even when the close handshake can't complete.
                connection._finalize_closed()
        self._connections.clear()
        self.closed = True

    def check(self, now_ms: int) -> bool:  # noqa: ARG002 - runner contract
        """Return ``True`` if there's work to do this tick."""
        return not self.closed

    def handle(self, now_ms: int) -> None:
        """Accept new connections and advance every active connection one tick."""
        if self.closed:
            return
        self._accept_pending(now_ms)
        # Snapshot the list: a connection finalizing inside handle() may mutate it.
        for connection in list(self._connections):
            if connection.state == WebSocketState.CLOSED:
                if connection in self._connections:
                    self._connections.remove(connection)
                continue
            connection.handle(now_ms)
            # A callback may call server.close(), clearing every connection; stop if so.
            if self.closed:
                return
            if (
                connection.state == WebSocketState.CLOSED
                and connection in self._connections
            ):
                self._connections.remove(connection)

    def _accept_pending(self, now_ms: int) -> None:
        while True:
            if len(self._connections) >= self._max_connections:
                return
            try:
                accepted = self._listener.accept()
            except OSError as accept_error:
                if accept_error.errno == errno.EAGAIN:
                    return
                self.last_error = accept_error
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
                max_inbound_queue_size=self._max_inbound_queue_size,
                ticks=self._ticks,
                on_connection_callback=self._on_connection,
            )
            self._connections.append(connection)
