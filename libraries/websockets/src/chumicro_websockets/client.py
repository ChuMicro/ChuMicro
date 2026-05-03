"""Runner-shaped WebSocket client built on chumicro-sockets + chumicro-timing.

:class:`WebSocketClient` is the entry point.  Runner-shaped per
Decision 0014 — :meth:`check(now_ms) -> bool` reports whether work is
pending; :meth:`handle(now_ms)` performs one tick of progress.  No
threads, no async — cooperative dispatch in the caller's tick loop.
The canonical promise (Decision 0045): an LED can keep blinking on
the same board through the opening handshake, frame I/O, and the
close handshake.

Single-connection per client (Decision 0045 §1): two parallel
websocket sessions need two :class:`WebSocketClient` instances.
Mirrors :class:`chumicro_mqtt.MQTTClient`'s "one broker per client"
shape rather than :class:`chumicro_requests.HttpClient`'s
single-in-flight request pool — websockets are session-scoped, not
request-scoped.

Slice 2 of Decision 0045 (this file): client-side state machine,
``connect`` / ``send_text`` / ``send_binary`` / ``send_ping`` /
``close`` lifecycle, callbacks (``on_open`` / ``on_text`` /
``on_binary`` / ``on_ping`` / ``on_pong`` / ``on_close`` /
``on_oversized``), inbound fragmentation reassembly, control-frame
interleave, auto-pong on PING, optional auto-ping interval, all
the per-phase timeouts.
"""

from collections import deque

from chumicro_timing import ticks_add, ticks_diff, ticks_ms

from chumicro_websockets._wire import (
    CLOSE_BAD_DATA,
    CLOSE_INTERNAL_ERROR,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    CLOSE_TOO_BIG,
    CONTROL_OPCODES,
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
    HandshakeResponseParser,
    WebSocketBackpressureError,
    WebSocketHandshakeError,
    WebSocketProtocolError,
    WebSocketState,
    WebSocketStateError,
    WebSocketTimeoutError,
    derive_accept_key,
    encode_client_handshake,
    encode_close_payload,
    encode_frame,
    make_mask_key,
    make_websocket_key,
    parse_close_payload,
    parse_ws_url,
    validate_text_payload,
)

# ---------------------------------------------------------------------------
# WhenOversized policy
# ---------------------------------------------------------------------------


class WhenOversized:
    """Policy for inbound messages exceeding ``max_message_bytes``.

    Mirrors :class:`chumicro_mqtt.WhenOversized` and
    :class:`chumicro_requests.WhenOversized`.  Decision 0045 §6 +
    `plans/patterns.md` §"WhenOversized policy".  Copy-don't-couple
    until a third user triggers extracting a shared enum.
    """

    #: Drop the rest of the in-progress message silently; the client
    #: stays connected and waits for the next message.  Use when
    #: occasional jumbo messages are fine to skip.
    DROP_SILENT = "drop_silent"

    #: Default.  Drop the message, fire ``client.on_oversized(reported_length)``
    #: if set, then close the connection with :data:`CLOSE_TOO_BIG`
    #: (RFC 6455 §7.4.1, code 1009).  Keeps the application informed.
    DROP_WITH_EVENT = "drop_with_event"

    #: Treat as a protocol error: close immediately with
    #: :data:`CLOSE_TOO_BIG`.  Use when application invariants assume
    #: messages fit within the configured cap and seeing a larger one
    #: means peer or transport corruption.
    DISCONNECT = "disconnect"


# ---------------------------------------------------------------------------
# Connecting sub-states
# ---------------------------------------------------------------------------


class ConnectingPhase:
    """Sub-states inside the top-level :data:`WebSocketState.CONNECTING`.

    The opening handshake is two distinct I/O phases — sending the
    upgrade request, then receiving + validating the 101 response.
    Tracking which sub-phase we're in lets ``handle()`` know whether
    to write or read.
    """

    SENDING_HANDSHAKE = "sending_handshake"
    RECEIVING_HANDSHAKE = "receiving_handshake"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_callback(*_args, **_kwargs):
    """Default no-op callback so handlers can be stored unconditionally."""
    return None


def _new_tx_queue(maxlen):
    """Return a fresh outbound ``deque`` sized at *maxlen*.

    Cross-runtime: MicroPython / CircuitPython require ``flags=1`` to
    enable ``appendleft`` (used to push close-frames to the front of
    the queue so they jump the line); CPython's deque needs no flag.
    Mirrors :func:`chumicro_mqtt.client._new_tx_queue` — see
    `plans/patterns.md` §"FIFO queues use ``deque``, not ``list``".
    """
    try:
        return deque((), maxlen, 1)
    except TypeError:  # CPython
        return deque((), maxlen)


def _force_non_blocking(socket):
    """Best-effort ``setblocking(False)`` on a chumicro-sockets socket.

    Mirrors :func:`chumicro_requests.client._force_non_blocking` and
    :func:`chumicro_mqtt.client._force_non_blocking`.  The tick-based
    RX path expects ``recv_into`` to raise EAGAIN when no data is
    available, never to block — but MicroPython's stdlib socket
    starts blocking, so we enforce here.
    """
    setblocking = getattr(socket, "setblocking", None)
    if setblocking is None:
        return
    try:
        setblocking(False)
    except (OSError, AttributeError):  # pragma: no cover - defensive
        pass


def _is_eagain(exception):
    """Return True if *exception* indicates "no data ready / would block".

    Cross-runtime: CPython raises :class:`BlockingIOError` (errno 11
    on Linux, 35 on macOS); MicroPython + CircuitPython raise
    :class:`OSError` with ``errno == EAGAIN``.  Some adapters surface
    the no-data condition as a return of ``0`` or ``None`` from
    ``recv_into`` — those code paths handle that separately.
    """
    errno_attr = getattr(exception, "errno", None)
    if errno_attr in (11, 35, 9):  # EAGAIN, EWOULDBLOCK on macOS, EBADF
        return True
    return isinstance(exception, BlockingIOError)


# ---------------------------------------------------------------------------
# WebSocketClient
# ---------------------------------------------------------------------------


class WebSocketClient:
    """Non-blocking RFC 6455 WebSocket client.

    Construct with a *connection_factory* + user knobs, configure
    callbacks, then call :meth:`connect`.  Drive via :meth:`check` /
    :meth:`handle` from a runner tick or a hand-rolled loop.  All
    callbacks fire from :meth:`handle` — never from a thread or
    interrupt.

    Args:
        connection_factory: ``callable(host: str, port: int, use_tls: bool)
            -> TCPClientSocket`` (matching :func:`chumicro_sockets.tcp_client_socket`
            / :func:`tls_client_socket`).  Called once per :meth:`connect`.
        max_message_bytes: Cap on the assembled inbound message size
            (sum of fragment payloads).  Default :data:`DEFAULT_MAX_MESSAGE_BYTES`
            (16 KB).  Per-frame caps land at the same value.
        recv_budget_per_tick: Max bytes drained from the socket per
            :meth:`handle` call.  Default :data:`DEFAULT_RECV_BUDGET_PER_TICK`
            (1024 B).  Keeps tick latency LED-friendly when a large
            inbound message is mid-flight.
        send_budget_per_tick: Max bytes pushed to the socket per
            :meth:`handle` call.  Default :data:`DEFAULT_SEND_BUDGET_PER_TICK`
            (1024 B).
        max_tx_queue_size: Bound on the outbound message queue.
            Default :data:`DEFAULT_MAX_TX_QUEUE_SIZE` (8).  Enqueueing
            past the cap raises :class:`WebSocketBackpressureError`.
        when_oversized: Policy for inbound messages above
            ``max_message_bytes``.  Default
            :attr:`WhenOversized.DROP_WITH_EVENT`.
        ping_interval_ms: If set, send an unsolicited PING on this
            cadence to keep the connection alive.  Default ``None``
            (disabled — most servers drive their own keep-alive).
        pong_timeout_ms: If a PING has been outstanding for this long
            without a PONG, close with :data:`CLOSE_INTERNAL_ERROR`.
            Default :data:`DEFAULT_PONG_TIMEOUT_MS` (30 s).  Only
            consulted when :attr:`ping_interval_ms` is set.
        handshake_timeout_ms: Total opening-handshake budget.
            Default :data:`DEFAULT_HANDSHAKE_TIMEOUT_MS` (10 s).
        close_timeout_ms: After we send CLOSE, how long to wait for
            the peer's CLOSE before forcing TCP teardown.  Default
            :data:`DEFAULT_CLOSE_TIMEOUT_MS` (5 s).
        ticks_ms_func / ticks_add_func / ticks_diff_func: Inject
            fakes for testing.  Default to :mod:`chumicro_timing`.
    """

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
        self._connection_factory = connection_factory
        self._max_message_bytes = max_message_bytes
        self._recv_budget_per_tick = recv_budget_per_tick
        self._send_budget_per_tick = send_budget_per_tick
        self._max_tx_queue_size = max_tx_queue_size
        self._when_oversized = when_oversized
        self._ping_interval_ms = ping_interval_ms
        self._pong_timeout_ms = pong_timeout_ms
        self._handshake_timeout_ms = handshake_timeout_ms
        self._close_timeout_ms = close_timeout_ms

        self._ticks_ms = ticks_ms_func
        self._ticks_add = ticks_add_func
        self._ticks_diff = ticks_diff_func

        # Pre-allocated recv scratch buffer — reused on every tick so
        # we don't churn the heap with ~1 KB allocations per handle()
        # call.  Live-board MemoryError on Pi Pico W (124 KB free heap)
        # caught the per-call allocation; matches the chumicro-mqtt
        # PacketDecoder.fill_buffer() pre-allocation pattern.
        self._recv_buffer = bytearray(self._recv_budget_per_tick)
        self._recv_view = memoryview(self._recv_buffer)

        self._state = WebSocketState.CONNECTING
        # Set on the first connect() call; before then state stays
        # CONNECTING but with no socket / no parsers — `connect()` is
        # what actually kicks off any I/O.  Use a separate flag to
        # tell "constructed but not yet connect()ed" from "in-flight
        # handshake".
        self._connect_called = False
        self._connecting_phase = None
        self._socket = None
        self._url = ""

        self._handshake_response_parser = None
        self._handshake_send_buffer = None
        self._handshake_send_offset = 0

        # FrameParser for inbound; created at connect() time so
        # max_message_bytes propagates.
        self._frame_parser = None
        # Bytes left over from the handshake parse (start of the
        # framing stream) — fed into the frame parser on the first
        # post-handshake handle() tick.
        self._post_handshake_carry = b""

        # Outbound queue of pre-encoded frame `bytes`.
        self._tx_queue = _new_tx_queue(max_tx_queue_size + 8)
        self._tx_partial = None  # (bytes, offset) when last send was short.

        # Inbound message reassembly.
        self._inbound_message_buffer = bytearray()
        self._inbound_message_opcode = None  # TEXT or BINARY when fragmented
        self._inbound_oversized = False  # True after we crossed the cap

        # Timeouts.
        self._handshake_deadline_ticks = None
        self._close_deadline_ticks = None
        self._next_auto_ping_ticks = None
        self._pending_ping_deadline_ticks = None  # set when we send a PING

        # Result fields.
        self._last_close_code = None
        self._last_close_reason = ""
        self._last_error = None

        # Callbacks default to no-ops.
        self.on_open = _no_callback
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
    def url(self):
        """The URL the client connected to (or ``""`` before :meth:`connect`)."""
        return self._url

    @property
    def last_close_code(self):
        """Close code seen / sent on shutdown (``None`` if no close was negotiated)."""
        return self._last_close_code

    @property
    def last_close_reason(self):
        """Reason string seen / sent on shutdown (``""`` if absent)."""
        return self._last_close_reason

    @property
    def last_error(self):
        """The :class:`WebSocketError` that ended the session, or ``None``."""
        return self._last_error

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

        Non-blocking modulo the *connection_factory* call (which itself
        may block briefly through DNS + TCP + TLS handshake — same
        contract as :func:`chumicro_sockets.tcp_client_socket`).  After
        :meth:`connect` returns, the client is in
        :data:`WebSocketState.CONNECTING`; subsequent :meth:`handle`
        ticks finish the upgrade and transition to OPEN.

        Args:
            url: ``ws://`` or ``wss://`` URL.
            timeout_ms: Override :attr:`handshake_timeout_ms` for this
                connection.  ``None`` keeps the constructor default.
            extra_headers: Optional iterable / ``dict`` /
                :class:`CaseInsensitiveDict` to merge in alongside
                the mandatory upgrade headers — useful for
                ``Cookie`` / ``Authorization`` / ``Origin``.

        Raises:
            WebSocketStateError: Called more than once on the same
                client.  Reconnection means a fresh client.
            WebSocketURLError: *url* doesn't parse as ``ws://`` / ``wss://``.
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
        self._frame_parser = FrameParser(max_payload_bytes=self._max_message_bytes)

        budget_ms = self._handshake_timeout_ms if timeout_ms is None else timeout_ms
        self._handshake_deadline_ticks = self._ticks_add(
            self._ticks_ms(),
            budget_ms,
        )

        self._state = WebSocketState.CONNECTING
        self._connecting_phase = ConnectingPhase.SENDING_HANDSHAKE

    def send_text(self, text: str) -> None:
        """Enqueue a text message.

        Args:
            text: UTF-8 string payload.

        Raises:
            WebSocketStateError: Not in :data:`WebSocketState.OPEN`.
            WebSocketBackpressureError: TX queue is full.
        """
        if self._state != WebSocketState.OPEN:
            raise WebSocketStateError(
                f"send_text() requires OPEN state, was {self._state}",
            )
        payload = text.encode("utf-8")
        self._enqueue_user_frame(OPCODE_TEXT, payload)

    def send_binary(self, data) -> None:
        """Enqueue a binary message.

        Args:
            data: ``bytes`` / ``bytearray`` / ``memoryview`` payload.

        Raises:
            WebSocketStateError: Not in :data:`WebSocketState.OPEN`.
            WebSocketBackpressureError: TX queue is full.
        """
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
        """Send a PING control frame.

        The peer is required (RFC 6455 §5.5.2) to reply with a PONG
        echoing *payload*.  When :attr:`ping_interval_ms` is set, the
        client sends pings automatically — manual :meth:`send_ping`
        is for application-level ping/pong, not keep-alive.

        Args:
            payload: Up to 125 bytes (RFC 6455 §5.5).

        Raises:
            WebSocketStateError: Not in :data:`WebSocketState.OPEN`.
            WebSocketBackpressureError: TX queue is full.
            WebSocketProtocolError: *payload* > 125 bytes.
        """
        if self._state != WebSocketState.OPEN:
            raise WebSocketStateError(
                f"send_ping() requires OPEN state, was {self._state}",
            )
        self._enqueue_user_frame(OPCODE_PING, bytes(payload))
        self._arm_pong_deadline()

    def close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        """Initiate a graceful close handshake.

        Sends a CLOSE frame with *code* + *reason* and transitions to
        :data:`WebSocketState.CLOSING`.  The TCP socket stays open until
        the peer's CLOSE arrives or :attr:`close_timeout_ms` elapses.

        Args:
            code: RFC 6455 §7.4 status code.  Default
                :data:`CLOSE_NORMAL` (1000).
            reason: UTF-8 string explaining the close.

        Raises:
            WebSocketStateError: Already CLOSING or CLOSED.
        """
        if self._state in (WebSocketState.CLOSING, WebSocketState.CLOSED):
            raise WebSocketStateError(
                f"close() not allowed in state {self._state}",
            )
        self._send_close(code, reason)

    # ------------------------------------------------------------------
    # Runner contract
    # ------------------------------------------------------------------

    def check(self, now_ms: int) -> bool:
        """Return ``True`` if there's work to do on this tick.

        Cheap to call; safe to invoke before :meth:`connect` (returns
        ``False``).

        Args:
            now_ms: Current monotonic-ish millisecond reading.
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
        """Do one tick of progress.

        Drains a bounded amount of inbound bytes through the
        framing parser, then drains a bounded amount of outbound
        bytes from the TX queue.  All callbacks fire here.  Safe to
        call when there's no work — returns quickly.

        Args:
            now_ms: Current monotonic-ish millisecond reading.
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
    # Internal: enqueue
    # ------------------------------------------------------------------

    def _enqueue_user_frame(self, opcode: int, payload: bytes) -> None:
        """Encode + queue an outbound frame, enforcing the user-visible cap."""
        if len(self._tx_queue) >= self._max_tx_queue_size:
            raise WebSocketBackpressureError(
                f"TX queue is full ({self._max_tx_queue_size} messages); "
                f"call handle() to drain before sending more",
            )
        encoded = encode_frame(opcode, payload, fin=True, mask=make_mask_key())
        self._tx_queue.append(encoded)

    def _enqueue_internal_frame(self, opcode: int, payload: bytes) -> None:
        """Queue a system-driven frame (close, pong, auto-ping) — no cap check.

        Internal frames bypass ``max_tx_queue_size`` because the queue
        was sized for user payloads + headroom.  The deque's structural
        ``maxlen`` (= max_tx_queue_size + 8) bounds heap regardless.
        """
        encoded = encode_frame(opcode, payload, fin=True, mask=make_mask_key())
        self._tx_queue.append(encoded)

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
    # Internal: inbound drain (post-handshake)
    # ------------------------------------------------------------------

    def _drain_inbound(self) -> None:
        """Read up to recv_budget bytes and feed the frame parser."""
        chunk = self._recv_chunk(self._recv_budget_per_tick)
        if chunk is None:
            return
        if not chunk:
            # Peer closed without sending CLOSE — abnormal close.  RFC
            # 6455 §7.1.5 — no status code, surface CLOSE_ABNORMAL via
            # last_error.
            self._fail_with_error(
                WebSocketProtocolError(
                    "peer closed TCP without sending a CLOSE frame",
                ),
            )
            return
        self._feed_frame_bytes(chunk)

    def _feed_frame_bytes(self, chunk: bytes) -> None:
        """Push *chunk* through :class:`FrameParser`, handling completed frames."""
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
                if self._state in (WebSocketState.CLOSED,):
                    return
                self._frame_parser.reset()

    def _dispatch_frame(self) -> None:
        """Route a just-completed frame through the message-level state machine."""
        opcode = self._frame_parser.opcode
        fin = self._frame_parser.fin
        had_mask = self._frame_parser.had_mask
        payload = self._frame_parser.payload

        # Servers MUST NOT mask outbound frames per RFC 6455 §5.1.
        if had_mask:
            self._send_close(
                CLOSE_PROTOCOL_ERROR,
                "server frame must not be masked",
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
        if opcode in CONTROL_OPCODES:  # pragma: no cover - exhaustive
            self._send_close(
                CLOSE_PROTOCOL_ERROR,
                f"unhandled control opcode 0x{opcode:x}",
            )
            return

        # Data frame — TEXT, BINARY, or CONT.
        self._handle_data_frame(opcode, fin, payload)

    def _handle_data_frame(self, opcode: int, fin: bool, payload: bytes) -> None:
        """Reassemble fragmented messages, applying oversize policy."""
        if opcode == OPCODE_CONTINUATION:
            if self._inbound_message_opcode is None:
                self._send_close(
                    CLOSE_PROTOCOL_ERROR,
                    "CONTINUATION frame with no in-progress message",
                )
                return
            self._extend_inbound_buffer(payload)
        else:
            # TEXT or BINARY — must NOT arrive mid-fragmentation.
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

        # Final fragment (or single-frame message) — emit and reset.
        if self._inbound_oversized:
            # Already triggered policy mid-stream; finalize it.
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
        """Append *payload* to the reassembly buffer, applying the cap."""
        if self._inbound_oversized:
            return  # already over — wait for FIN to finalize
        projected = len(self._inbound_message_buffer) + len(payload)
        if projected > self._max_message_bytes:
            self._inbound_oversized = True
            return
        self._inbound_message_buffer.extend(payload)

    def _finish_oversized_message(self) -> None:
        """Apply the WhenOversized policy at message-FIN time."""
        reported_length = len(self._inbound_message_buffer)
        # The buffer is incomplete — we stopped extending once we
        # crossed the cap.  Surface the size we observed.
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
        """Clear reassembly state for the next message."""
        self._inbound_message_buffer = bytearray()
        self._inbound_message_opcode = None
        self._inbound_oversized = False

    def _handle_close_frame(self, payload: bytes) -> None:
        """Process inbound CLOSE — record + reciprocate or finalize."""
        try:
            code, reason = parse_close_payload(payload)
        except WebSocketProtocolError as parse_error:
            # Even close frames must be valid; respond with protocol error.
            self._send_close(CLOSE_PROTOCOL_ERROR, str(parse_error))
            self._last_error = parse_error
            return

        if self._state == WebSocketState.CLOSING:
            # We initiated.  Peer's CLOSE finishes the handshake.
            if self._last_close_code is None:
                self._last_close_code = code
                self._last_close_reason = reason
            self._finalize_closed()
            return

        # Peer initiated.  Echo their close code back per RFC 6455 §5.5.1.
        self._last_close_code = code
        self._last_close_reason = reason
        self._send_close(code if code is not None else CLOSE_NORMAL, "")
        self._finalize_closed()

    def _handle_ping_frame(self, payload: bytes) -> None:
        """Auto-pong inbound PING + fire user callback."""
        self._enqueue_internal_frame(OPCODE_PONG, payload)
        self.on_ping(payload)

    def _handle_pong_frame(self, payload: bytes) -> None:
        """Clear the pending-pong deadline and fire user callback."""
        self._pending_ping_deadline_ticks = None
        self.on_pong(payload)

    # ------------------------------------------------------------------
    # Internal: outbound drain
    # ------------------------------------------------------------------

    def _drain_outbound(self) -> None:
        """Push as many queued bytes to the socket as the budget allows."""
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
            except Exception as send_error:  # noqa: BLE001 — narrow below
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
        """Non-blocking recv; ``bytes``, ``b""`` on EOF, or ``None`` on EAGAIN.

        Reads into the pre-allocated :attr:`_recv_buffer` (sized to
        ``recv_budget_per_tick`` at construction time) so we don't
        churn the heap.  Caller gets back a fresh ``bytes`` slice of
        exactly the bytes received.
        """
        cap = max_bytes if max_bytes <= len(self._recv_buffer) else len(self._recv_buffer)
        try:
            received = self._socket.recv_into(self._recv_view[:cap], cap)
        except Exception as recv_error:  # noqa: BLE001 — narrow below
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
        """Queue a CLOSE frame and transition to CLOSING.

        Idempotent — a second :meth:`_send_close` while already
        CLOSING is a no-op (caller may have sent the close themselves
        and the peer's CLOSE then arrives).
        """
        if self._state in (WebSocketState.CLOSING, WebSocketState.CLOSED):
            return
        try:
            payload = encode_close_payload(code, reason)
        except WebSocketProtocolError:
            # Reserved close code or oversize reason — fall back to
            # a no-body close so we still trigger the handshake.
            payload = b""
        self._enqueue_internal_frame(OPCODE_CLOSE, payload)
        # Only record close code + reason if not already set — preserves
        # the peer's values when this is the echo half of a peer-initiated
        # close handshake (where _handle_close_frame stored peer's
        # code/reason before calling us).
        if self._last_close_code is None:
            self._last_close_code = code
            self._last_close_reason = reason
        self._state = WebSocketState.CLOSING
        self._close_deadline_ticks = self._ticks_add(
            self._ticks_ms(),
            self._close_timeout_ms,
        )

    def _finalize_closed(self) -> None:
        """Drain any pending close frame, then close the socket and notify."""
        # Try to flush the CLOSE frame so the peer sees our reply.
        if self._tx_queue or self._tx_partial is not None:
            self._drain_outbound()
        try:
            self._socket.close()
        except Exception:  # noqa: BLE001 - best-effort socket teardown
            pass
        self._state = WebSocketState.CLOSED
        self._close_deadline_ticks = None
        self._next_auto_ping_ticks = None
        self._pending_ping_deadline_ticks = None
        code = self._last_close_code if self._last_close_code is not None else CLOSE_NORMAL
        self.on_close(code, self._last_close_reason)

    def _fail_with_error(self, error) -> None:
        """Record *error*, force close, transition to CLOSED, fire on_close.

        Used by handshake failures, socket errors, and timeouts.
        """
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
        self._next_auto_ping_ticks = None
        self._pending_ping_deadline_ticks = None
        self.on_close(self._last_close_code, self._last_close_reason)

    # ------------------------------------------------------------------
    # Internal: timeouts + auto-ping
    # ------------------------------------------------------------------

    def _check_timeouts(self, now_ms: int) -> bool:
        """Trip any expired deadline and return ``True`` if we transitioned."""
        if self._handshake_deadline_ticks is not None:
            if self._ticks_diff(self._handshake_deadline_ticks, now_ms) <= 0:
                self._fail_with_error(
                    WebSocketTimeoutError(
                        f"handshake exceeded {self._handshake_timeout_ms} ms",
                    ),
                )
                return True
        if self._close_deadline_ticks is not None:
            if self._ticks_diff(self._close_deadline_ticks, now_ms) <= 0:
                # Force closed even though peer didn't echo CLOSE.
                self._last_error = WebSocketTimeoutError(
                    f"peer did not send CLOSE within {self._close_timeout_ms} ms",
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

    def _arm_pong_deadline(self) -> None:
        """Set the pong-overdue watchdog if not already armed."""
        if self._pong_timeout_ms is None:
            return
        if self._pending_ping_deadline_ticks is not None:
            return  # earlier ping still outstanding — keep its deadline
        self._pending_ping_deadline_ticks = self._ticks_add(
            self._ticks_ms(),
            self._pong_timeout_ms,
        )
