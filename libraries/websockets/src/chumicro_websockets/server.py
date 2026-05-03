"""Runner-shaped WebSocket server built on chumicro-sockets + chumicro-timing.

:class:`WebSocketServer` is the entry point.  Owns a TCP (or TLS)
listening socket handed in at construction time, accepts inbound
connections, dispatches them as :class:`Connection` objects through
the user's ``on_connection`` callback, and drives the per-connection
state machines from its own :meth:`check` / :meth:`handle` runner
contract.

Standalone-port shape only in v1 (Decision 0045 §4) — sharing a
port with :class:`chumicro_http_server.HttpServer` is a v2 ask
(would require peek-then-route on the HTTP request line).  The
optional *accept_path* knob lets a server filter inbound upgrades
by URI path so a path-based router can sit in front of multiple
ports.

Slice 3 of Decision 0045 (this file): :class:`WebSocketServer`
accept loop + bounded multi-connection management; :class:`Connection`
per-connection state machine (READING_REQUEST → SENDING_RESPONSE →
OPEN → CLOSING → CLOSED) sharing the framing pipeline + close
handshake shape with :class:`WebSocketClient`.
"""

from chumicro_timing import ticks_add, ticks_diff, ticks_ms

from chumicro_websockets._wire import (
    CLOSE_BAD_DATA,
    CLOSE_INTERNAL_ERROR,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    CLOSE_TOO_BIG,
    DEFAULT_CLOSE_TIMEOUT_MS,
    DEFAULT_HANDSHAKE_TIMEOUT_MS,
    DEFAULT_MAX_MESSAGE_BYTES,
    DEFAULT_MAX_TX_QUEUE_SIZE,
    DEFAULT_PONG_TIMEOUT_MS,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_SEND_BUDGET_PER_TICK,
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_CONTINUATION,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    FrameParser,
    FrameParseState,
    HandshakeParseState,
    HandshakeRequestParser,
    WebSocketBackpressureError,
    WebSocketHandshakeError,
    WebSocketProtocolError,
    WebSocketState,
    WebSocketStateError,
    WebSocketTimeoutError,
    encode_close_payload,
    encode_frame,
    encode_server_handshake_response,
    encode_server_rejection,
    parse_close_payload,
    validate_text_payload,
)
from chumicro_websockets.client import (
    WhenOversized,
    _force_non_blocking,
    _is_eagain,
    _new_tx_queue,
    _no_callback,
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


class Connection:
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

    def __init__(
        self,
        socket,
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
        ticks_ms_func,
        ticks_add_func,
        ticks_diff_func,
        on_connection_callback,
    ) -> None:
        self._socket = socket
        _force_non_blocking(self._socket)
        self._accept_path = accept_path
        self._max_message_bytes = max_message_bytes
        self._recv_budget_per_tick = recv_budget_per_tick
        self._send_budget_per_tick = send_budget_per_tick
        self._max_tx_queue_size = max_tx_queue_size
        self._when_oversized = when_oversized
        self._pong_timeout_ms = pong_timeout_ms
        self._close_timeout_ms = close_timeout_ms
        self._on_connection_callback = on_connection_callback

        self._ticks_ms = ticks_ms_func
        self._ticks_add = ticks_add_func
        self._ticks_diff = ticks_diff_func

        # Pre-allocated recv scratch buffer — see WebSocketClient for rationale.
        self._recv_buffer = bytearray(self._recv_budget_per_tick)
        self._recv_view = memoryview(self._recv_buffer)

        self._state = WebSocketState.CONNECTING
        self._handshake_phase = ServerHandshakePhase.READING_REQUEST
        self._handshake_request_parser = HandshakeRequestParser()
        self._handshake_response_buffer = None
        self._handshake_response_offset = 0

        # Set when reaching OPEN.
        self._frame_parser = FrameParser(max_payload_bytes=max_message_bytes)
        self._post_handshake_carry = b""

        self._tx_queue = _new_tx_queue(max_tx_queue_size + 8)
        self._tx_partial = None

        self._inbound_message_buffer = bytearray()
        self._inbound_message_opcode = None
        self._inbound_oversized = False

        self._handshake_deadline_ticks = self._ticks_add(
            self._ticks_ms(),
            handshake_timeout_ms,
        )
        self._close_deadline_ticks = None
        self._pending_ping_deadline_ticks = None

        self._request_path = ""
        self._request_headers = None
        self._last_close_code = None
        self._last_close_reason = ""
        self._last_error = None

        # Callbacks default to no-ops; the user wires real ones inside
        # *on_connection* (called once when this connection reaches OPEN).
        self.on_text = _no_callback
        self.on_binary = _no_callback
        self.on_ping = _no_callback
        self.on_pong = _no_callback
        self.on_close = _no_callback
        self.on_oversized = _no_callback

    # ------------------------------------------------------------------
    # Public observation
    # ------------------------------------------------------------------

    @property
    def state(self):
        """Current :class:`WebSocketState`."""
        return self._state

    @property
    def request_path(self):
        """URI path from the inbound upgrade request (``""`` until OPEN)."""
        return self._request_path

    @property
    def request_headers(self):
        """Headers from the inbound upgrade request (``None`` until OPEN)."""
        return self._request_headers

    @property
    def last_close_code(self):
        """Close code seen / sent on shutdown (``None`` if no close was negotiated)."""
        return self._last_close_code

    @property
    def last_close_reason(self):
        """Reason string seen / sent on shutdown."""
        return self._last_close_reason

    @property
    def last_error(self):
        """The :class:`WebSocketError` that ended this connection, or ``None``."""
        return self._last_error

    # ------------------------------------------------------------------
    # Public send / close
    # ------------------------------------------------------------------

    def send_text(self, text: str) -> None:
        """Enqueue a text message.  Server-side outbound is unmasked."""
        if self._state != WebSocketState.OPEN:
            raise WebSocketStateError(
                f"send_text() requires OPEN state, was {self._state}",
            )
        self._enqueue_user_frame(OPCODE_TEXT, text.encode("utf-8"))

    def send_binary(self, data) -> None:
        """Enqueue a binary message.  Server-side outbound is unmasked."""
        if self._state != WebSocketState.OPEN:
            raise WebSocketStateError(
                f"send_binary() requires OPEN state, was {self._state}",
            )
        if isinstance(data, (bytearray, memoryview)):
            data = bytes(data)
        elif not isinstance(data, bytes):
            raise TypeError(
                f"send_binary() requires bytes, bytearray, or memoryview; "
                f"got {type(data).__name__}",
            )
        self._enqueue_user_frame(OPCODE_BINARY, data)

    def send_ping(self, payload: bytes = b"") -> None:
        """Send a PING control frame; arms the pong-overdue watchdog."""
        if self._state != WebSocketState.OPEN:
            raise WebSocketStateError(
                f"send_ping() requires OPEN state, was {self._state}",
            )
        self._enqueue_user_frame(OPCODE_PING, bytes(payload))
        self._arm_pong_deadline()

    def close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        """Initiate the close handshake."""
        if self._state in (WebSocketState.CLOSING, WebSocketState.CLOSED):
            raise WebSocketStateError(
                f"close() not allowed in state {self._state}",
            )
        self._send_close(code, reason)

    # ------------------------------------------------------------------
    # Server-driven handle (called by WebSocketServer)
    # ------------------------------------------------------------------

    def check(self, now_ms: int) -> bool:
        """Return ``True`` if there's work to do for this connection."""
        if self._state == WebSocketState.CLOSED:
            return False
        return True

    def handle(self, now_ms: int) -> None:
        """One tick of progress for this connection."""
        if self._state == WebSocketState.CLOSED:
            return

        if self._check_timeouts(now_ms):
            return

        if self._state == WebSocketState.CONNECTING:
            if self._handshake_phase == ServerHandshakePhase.READING_REQUEST:
                self._receive_handshake_chunk()
            elif self._handshake_phase == ServerHandshakePhase.SENDING_RESPONSE:
                self._send_handshake_chunk()
            return

        # OPEN / CLOSING — drain inbound first, then outbound.
        self._drain_inbound()
        self._drain_outbound()

    # ------------------------------------------------------------------
    # Internal: handshake — server reads first, then sends 101
    # ------------------------------------------------------------------

    def _receive_handshake_chunk(self) -> None:
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
        self._handshake_response_buffer = encode_server_handshake_response(
            self._handshake_request_parser.client_key,
        )
        self._handshake_response_offset = 0
        self._request_path = self._handshake_request_parser.path
        self._request_headers = self._handshake_request_parser.headers
        self._post_handshake_carry = self._handshake_request_parser.leftover
        self._handshake_phase = ServerHandshakePhase.SENDING_RESPONSE

    def _send_handshake_chunk(self) -> None:
        remaining = self._handshake_response_buffer[
            self._handshake_response_offset:
        ]
        if not remaining:
            self._enter_open()
            return
        chunk = remaining[: self._send_budget_per_tick]
        try:
            sent = self._socket.send(chunk)
        except Exception as send_error:  # noqa: BLE001 - narrow below
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
        self._handshake_response_offset += sent
        if self._handshake_response_offset >= len(self._handshake_response_buffer):
            self._enter_open()

    def _enter_open(self) -> None:
        """Transition from sending-response to OPEN; fire user callback."""
        self._handshake_request_parser = None
        self._handshake_response_buffer = None
        self._handshake_phase = None
        self._handshake_deadline_ticks = None
        self._state = WebSocketState.OPEN
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
            self._feed_frame_bytes(self._post_handshake_carry)
            self._post_handshake_carry = b""

    def _reject_with_400(self, message: str) -> None:
        """Send a 400 Bad Request, then close."""
        body = message.encode("utf-8")
        self._send_rejection_response(400, "Bad Request", body)
        self._last_error = WebSocketHandshakeError(message)

    def _reject_with_404(self, message: str) -> None:
        """Send a 404 Not Found, then close."""
        body = message.encode("utf-8")
        self._send_rejection_response(404, "Not Found", body)
        self._last_error = WebSocketHandshakeError(message)

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
        self._state = WebSocketState.CLOSED
        self._handshake_deadline_ticks = None
        self.on_close(status_code, reason_phrase)

    # ------------------------------------------------------------------
    # Internal: enqueue
    # ------------------------------------------------------------------

    def _enqueue_user_frame(self, opcode: int, payload: bytes) -> None:
        if len(self._tx_queue) >= self._max_tx_queue_size:
            raise WebSocketBackpressureError(
                f"TX queue is full ({self._max_tx_queue_size} messages); "
                f"call WebSocketServer.handle() to drain before sending more",
            )
        # Server-side outbound is NEVER masked per RFC 6455 §5.1.
        encoded = encode_frame(opcode, payload, fin=True, mask=None)
        self._tx_queue.append(encoded)

    def _enqueue_internal_frame(self, opcode: int, payload: bytes) -> None:
        encoded = encode_frame(opcode, payload, fin=True, mask=None)
        self._tx_queue.append(encoded)

    # ------------------------------------------------------------------
    # Internal: inbound + outbound (post-handshake)
    # ------------------------------------------------------------------

    def _drain_inbound(self) -> None:
        chunk = self._recv_chunk(self._recv_budget_per_tick)
        if chunk is None:
            return
        if not chunk:
            self._fail_with_error(
                WebSocketProtocolError(
                    "client closed TCP without sending a CLOSE frame",
                ),
            )
            return
        self._feed_frame_bytes(chunk)

    def _feed_frame_bytes(self, chunk: bytes) -> None:
        offset = 0
        while offset < len(chunk):
            try:
                consumed = self._frame_parser.feed(chunk[offset:])
            except WebSocketProtocolError as protocol_error:
                self._send_close(CLOSE_PROTOCOL_ERROR, str(protocol_error))
                self._last_error = protocol_error
                return
            offset += consumed
            if self._frame_parser.state == FrameParseState.FRAME_READY:
                self._dispatch_frame()
                if self._state == WebSocketState.CLOSED:
                    return
                self._frame_parser.reset()

    def _dispatch_frame(self) -> None:
        opcode = self._frame_parser.opcode
        fin = self._frame_parser.fin
        had_mask = self._frame_parser.had_mask
        payload = self._frame_parser.payload

        # Clients MUST mask outbound frames per RFC 6455 §5.1.
        if not had_mask:
            self._send_close(
                CLOSE_PROTOCOL_ERROR,
                "client frame must be masked",
            )
            return

        if opcode == OPCODE_CLOSE:
            self._handle_close_frame(payload)
            return
        if opcode == OPCODE_PING:
            self._handle_ping_frame(payload)
            return
        if opcode == OPCODE_PONG:
            self._handle_pong_frame(payload)
            return
        # Reserved opcodes (0xB-0xF) are caught upstream by FrameParser.
        # Anything that gets here is a data opcode (TEXT, BINARY, or CONT).
        self._handle_data_frame(opcode, fin, payload)

    def _handle_data_frame(self, opcode: int, fin: bool, payload: bytes) -> None:
        if opcode == OPCODE_CONTINUATION:
            if self._inbound_message_opcode is None:
                self._send_close(
                    CLOSE_PROTOCOL_ERROR,
                    "CONTINUATION frame with no in-progress message",
                )
                return
            self._extend_inbound_buffer(payload)
        else:
            if self._inbound_message_opcode is not None:
                self._send_close(
                    CLOSE_PROTOCOL_ERROR,
                    f"new {opcode:#x} frame in the middle of a fragmented message",
                )
                return
            self._inbound_message_opcode = opcode
            self._extend_inbound_buffer(payload)

        if not fin:
            return

        if self._inbound_oversized:
            self._finish_oversized_message()
            return

        message_opcode = self._inbound_message_opcode
        message_payload = bytes(self._inbound_message_buffer)
        self._reset_inbound_state()

        if message_opcode == OPCODE_TEXT:
            try:
                text = validate_text_payload(message_payload)
            except WebSocketProtocolError as utf8_error:
                self._send_close(CLOSE_BAD_DATA, str(utf8_error))
                self._last_error = utf8_error
                return
            self.on_text(text)
        else:
            self.on_binary(message_payload)

    def _extend_inbound_buffer(self, payload: bytes) -> None:
        if self._inbound_oversized:
            return
        projected = len(self._inbound_message_buffer) + len(payload)
        if projected > self._max_message_bytes:
            self._inbound_oversized = True
            return
        self._inbound_message_buffer.extend(payload)

    def _finish_oversized_message(self) -> None:
        reported_length = len(self._inbound_message_buffer)
        self._reset_inbound_state()
        policy = self._when_oversized
        if policy == WhenOversized.DROP_SILENT:
            return
        if policy == WhenOversized.DROP_WITH_EVENT:
            self.on_oversized(reported_length)
            self._send_close(
                CLOSE_TOO_BIG,
                f"message exceeded max_message_bytes={self._max_message_bytes}",
            )
            return
        if policy == WhenOversized.DISCONNECT:
            self._send_close(
                CLOSE_TOO_BIG,
                f"message exceeded max_message_bytes={self._max_message_bytes}",
            )

    def _reset_inbound_state(self) -> None:
        self._inbound_message_buffer = bytearray()
        self._inbound_message_opcode = None
        self._inbound_oversized = False

    def _handle_close_frame(self, payload: bytes) -> None:
        try:
            code, reason = parse_close_payload(payload)
        except WebSocketProtocolError as parse_error:
            self._send_close(CLOSE_PROTOCOL_ERROR, str(parse_error))
            self._last_error = parse_error
            return

        if self._state == WebSocketState.CLOSING:
            if self._last_close_code is None:
                self._last_close_code = code
                self._last_close_reason = reason
            self._finalize_closed()
            return

        # Peer-initiated.  Echo + finalize.
        self._last_close_code = code
        self._last_close_reason = reason
        self._send_close(code if code is not None else CLOSE_NORMAL, "")
        self._finalize_closed()

    def _handle_ping_frame(self, payload: bytes) -> None:
        self._enqueue_internal_frame(OPCODE_PONG, payload)
        self.on_ping(payload)

    def _handle_pong_frame(self, payload: bytes) -> None:
        self._pending_ping_deadline_ticks = None
        self.on_pong(payload)

    def _drain_outbound(self) -> None:
        budget = self._send_budget_per_tick
        while budget > 0:
            if self._tx_partial is None:
                if not self._tx_queue:
                    return
                self._tx_partial = (self._tx_queue.popleft(), 0)
            buffer, offset = self._tx_partial
            chunk = buffer[offset : offset + budget]
            try:
                sent = self._socket.send(chunk)
            except Exception as send_error:  # noqa: BLE001 - narrow below
                if _is_eagain(send_error):
                    return
                self._fail_with_error(
                    WebSocketProtocolError(
                        f"socket error during send: {send_error!r}",
                    ),
                )
                return
            if sent is None or sent == 0:
                return
            new_offset = offset + sent
            if new_offset >= len(buffer):
                self._tx_partial = None
            else:
                self._tx_partial = (buffer, new_offset)
            budget -= sent

    def _recv_chunk(self, max_bytes: int):
        cap = max_bytes if max_bytes <= len(self._recv_buffer) else len(self._recv_buffer)
        try:
            received = self._socket.recv_into(self._recv_view[:cap], cap)
        except Exception as recv_error:  # noqa: BLE001 - narrow below
            if _is_eagain(recv_error):
                return None
            self._fail_with_error(
                WebSocketProtocolError(
                    f"socket error during recv: {recv_error!r}",
                ),
            )
            return None
        if received is None:
            return None
        if received == 0:
            return b""
        return bytes(self._recv_buffer[:received])

    # ------------------------------------------------------------------
    # Internal: close + finalize
    # ------------------------------------------------------------------

    def _send_close(self, code: int, reason: str) -> None:
        if self._state in (WebSocketState.CLOSING, WebSocketState.CLOSED):
            return
        try:
            payload = encode_close_payload(code, reason)
        except WebSocketProtocolError:
            payload = b""
        self._enqueue_internal_frame(OPCODE_CLOSE, payload)
        if self._last_close_code is None:
            self._last_close_code = code
            self._last_close_reason = reason
        self._state = WebSocketState.CLOSING
        self._close_deadline_ticks = self._ticks_add(
            self._ticks_ms(),
            self._close_timeout_ms,
        )

    def _finalize_closed(self) -> None:
        if self._tx_queue or self._tx_partial is not None:
            self._drain_outbound()
        try:
            self._socket.close()
        except Exception:  # noqa: BLE001 - best-effort
            pass
        self._state = WebSocketState.CLOSED
        self._close_deadline_ticks = None
        self._pending_ping_deadline_ticks = None
        code = self._last_close_code if self._last_close_code is not None else CLOSE_NORMAL
        self.on_close(code, self._last_close_reason)

    def _fail_with_error(self, error) -> None:
        if self._last_error is None:
            self._last_error = error
        if self._last_close_code is None:
            self._last_close_code = CLOSE_INTERNAL_ERROR
            self._last_close_reason = str(error)
        try:
            if self._socket is not None:
                self._socket.close()
        except Exception:  # noqa: BLE001 - best-effort
            pass
        self._state = WebSocketState.CLOSED
        self._handshake_deadline_ticks = None
        self._close_deadline_ticks = None
        self._pending_ping_deadline_ticks = None
        self.on_close(self._last_close_code, self._last_close_reason)

    # ------------------------------------------------------------------
    # Internal: timeouts
    # ------------------------------------------------------------------

    def _check_timeouts(self, now_ms: int) -> bool:
        if self._handshake_deadline_ticks is not None:
            if self._ticks_diff(self._handshake_deadline_ticks, now_ms) <= 0:
                self._fail_with_error(
                    WebSocketTimeoutError(
                        "handshake exceeded budget",
                    ),
                )
                return True
        if self._close_deadline_ticks is not None:
            if self._ticks_diff(self._close_deadline_ticks, now_ms) <= 0:
                self._last_error = WebSocketTimeoutError(
                    f"client did not send CLOSE within {self._close_timeout_ms} ms",
                )
                self._finalize_closed()
                return True
        if self._pending_ping_deadline_ticks is not None:
            if self._ticks_diff(self._pending_ping_deadline_ticks, now_ms) <= 0:
                self._fail_with_error(
                    WebSocketTimeoutError(
                        f"no PONG within {self._pong_timeout_ms} ms of last PING",
                    ),
                )
                return True
        return False

    def _arm_pong_deadline(self) -> None:
        if self._pong_timeout_ms is None:
            return
        if self._pending_ping_deadline_ticks is not None:
            return
        self._pending_ping_deadline_ticks = self._ticks_add(
            self._ticks_ms(),
            self._pong_timeout_ms,
        )


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
    :data:`CLOSE_INTERNAL_ERROR`.  Standalone-port shape only in v1
    (Decision 0045 §4); ``accept_path`` filters by URI path with 404
    on mismatch.

    Knobs: ``max_connections`` (default 2; inbound accepts past the
    cap close immediately to bound heap + per-tick work);
    ``max_message_bytes`` / ``recv_budget_per_tick`` /
    ``send_budget_per_tick`` / ``max_tx_queue_size`` / ``when_oversized`` /
    ``pong_timeout_ms`` / ``handshake_timeout_ms`` /
    ``close_timeout_ms`` — same semantics as
    :class:`WebSocketClient`, applied per-connection;
    ``ticks_ms_func`` / ``ticks_add_func`` / ``ticks_diff_func`` —
    inject fakes for testing.
    """

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
        ticks_ms_func=ticks_ms,
        ticks_add_func=ticks_add,
        ticks_diff_func=ticks_diff,
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

        self._ticks_ms = ticks_ms_func
        self._ticks_add = ticks_add_func
        self._ticks_diff = ticks_diff_func

        self._connections: list[Connection] = []
        self._closed = False

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

    @property
    def closed(self) -> bool:
        """``True`` after :meth:`close` — listener teardown done."""
        return self._closed

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Stop accepting new connections + close every active session.
        Per-connection ``on_close`` callbacks fire as they finalize.
        After :meth:`close`, :meth:`check` returns ``False`` and
        :meth:`handle` is a no-op.
        """
        if self._closed:
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
        self._closed = True

    # ------------------------------------------------------------------
    # Runner contract
    # ------------------------------------------------------------------

    def check(self, now_ms: int) -> bool:
        """Return ``True`` if there's work to do this tick."""
        if self._closed:
            return False
        # Always True — accept loop must run, and any active connection
        # may need attention.  Conservative; cheap enough.
        return True

    def handle(self, now_ms: int) -> None:
        """Accept new connections + advance every active connection one tick."""
        if self._closed:
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

    def _accept_pending(self, now_ms: int) -> None:  # noqa: ARG002 — symmetry
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
                accept_path=self._accept_path,
                max_message_bytes=self._max_message_bytes,
                recv_budget_per_tick=self._recv_budget_per_tick,
                send_budget_per_tick=self._send_budget_per_tick,
                max_tx_queue_size=self._max_tx_queue_size,
                when_oversized=self._when_oversized,
                pong_timeout_ms=self._pong_timeout_ms,
                handshake_timeout_ms=self._handshake_timeout_ms,
                close_timeout_ms=self._close_timeout_ms,
                ticks_ms_func=self._ticks_ms,
                ticks_add_func=self._ticks_add,
                ticks_diff_func=self._ticks_diff,
                on_connection_callback=self._on_connection,
            )
            self._connections.append(connection)
