"""Shared OPEN/CLOSING/CLOSED machinery for WebSocketClient + Connection.

The opening-handshake half differs between client and server (request
direction, mask direction).  Everything *after* OPEN is identical
modulo two policies:

* Outbound mask — clients MUST mask, servers MUST NOT (RFC 6455 §5.1).
  Subclasses implement :meth:`_outbound_mask`.
* Inbound mask validation — clients reject masked inbound, servers
  reject unmasked.  Subclasses set :attr:`_inbound_mask_required`.
"""

from collections import deque

from chumicro_websockets._wire import (
    CLOSE_BAD_DATA,
    CLOSE_INTERNAL_ERROR,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    CLOSE_TOO_BIG,
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_CONTINUATION,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    FrameParser,
    FrameParseState,
    WebSocketBackpressureError,
    WebSocketHandshakeError,
    WebSocketProtocolError,
    WebSocketState,
    WebSocketStateError,
    WebSocketTimeoutError,
    encode_close_payload,
    encode_frame,
    parse_close_payload,
    validate_text_payload,
)


def _is_eagain(error):
    return getattr(error, "errno", None) in (11, 35)


#: A peer can legally fragment a message, including with empty
#: continuation frames, but an unbounded run of zero-byte fragments
#: never completes the message and never trips the size cap — a
#: no-progress liveness stall.  Closing after this many consecutive
#: empty fragments bounds it without penalising any sender that makes
#: byte progress.
_MAX_EMPTY_FRAGMENT_RUN = 64


# ---------------------------------------------------------------------------
# WhenOversized policy (lifted from client.py — used by both halves)
# ---------------------------------------------------------------------------


class WhenOversized:
    """Policy for inbound messages exceeding ``max_message_bytes``.
    Mirrors :class:`chumicro_mqtt.WhenOversized` /
    :class:`chumicro_requests.WhenOversized`.
    """

    #: Drop the message silently; stay connected for the next one.
    DROP_SILENT = "drop_silent"

    #: Default.  Drop the message, fire ``on_oversized(reported_length)``,
    #: and stay connected for the next inbound message.
    DROP_WITH_EVENT = "drop_with_event"

    #: Close immediately with :data:`CLOSE_TOO_BIG` — for when oversize
    #: means peer/transport corruption.
    DISCONNECT = "disconnect"


# ---------------------------------------------------------------------------
# Shared cross-runtime helpers
# ---------------------------------------------------------------------------


def _no_callback(*_args, **_kwargs):
    """Default no-op callback so handlers can be stored unconditionally."""
    return None


def _new_tx_queue(maxlen):
    """Return a fresh outbound ``deque`` sized at *maxlen*.

    MicroPython / CircuitPython require ``flags=1`` to enable
    ``appendleft`` (used to push close-frames to the front of the
    queue so they jump the line); CPython's deque needs no flag.
    Mirrors :func:`chumicro_mqtt.client._new_tx_queue`.
    """
    try:
        return deque((), maxlen, 1)
    except TypeError:  # CPython
        return deque((), maxlen)


def _force_non_blocking(socket):
    """Best-effort ``setblocking(False)`` on a chumicro-sockets socket.

    The tick-based RX path expects ``recv_into`` to raise EAGAIN when
    no data is available, never to block — but MicroPython's stdlib
    socket starts blocking, so we enforce here.
    """
    setblocking = getattr(socket, "setblocking", None)
    if setblocking is None:
        return
    try:
        setblocking(False)
    except OSError:  # pragma: no cover - defensive
        pass


# ---------------------------------------------------------------------------
# _BaseSession
# ---------------------------------------------------------------------------


class _BaseSession:
    """Shared OPEN/CLOSING/CLOSED state machine + framing pipeline.

    Subclass contract:

    * Override :attr:`_role_label` for error messages (``"client"`` /
      ``"server"``).
    * Override :attr:`_inbound_mask_required` (``False`` for client —
      server frames must NOT be masked; ``True`` for server — client
      frames MUST be masked).
    * Implement :meth:`_outbound_mask` to return either a fresh 4-byte
      mask key (client) or ``None`` (server).
    * Initialize the socket + frame parser by calling
      :meth:`_init_session_state` from your own ``__init__`` once the
      transport is ready.
    """

    _role_label: str = ""
    _inbound_mask_required: bool = False

    # -- shared state setup ------------------------------------------------

    def _init_session_state(
        self,
        socket,
        *,
        max_message_bytes: int,
        recv_budget_per_tick: int,
        send_budget_per_tick: int,
        max_tx_queue_size: int,
        when_oversized: str,
        pong_timeout_ms: int,
        handshake_timeout_ms: int,
        close_timeout_ms: int,
        ticks,
    ) -> None:
        self._socket = socket
        self._max_message_bytes = max_message_bytes
        self._recv_budget_per_tick = recv_budget_per_tick
        self._send_budget_per_tick = send_budget_per_tick
        self._max_tx_queue_size = max_tx_queue_size
        self._when_oversized = when_oversized
        self._pong_timeout_ms = pong_timeout_ms
        self._handshake_timeout_ms = handshake_timeout_ms
        self._close_timeout_ms = close_timeout_ms

        self._ticks = ticks

        # Pre-allocated recv scratch buffer — reused on every tick so we
        # don't churn the heap with ~1 KB allocations per handle() call.
        # Live-board MemoryError on Pi Pico W (124 KB free heap) caught
        # the per-call allocation; matches chumicro-mqtt's
        # PacketDecoder.fill_buffer() pre-allocation pattern.  Capped at
        # 512 B so a session configured with a large ``recv_budget_per_tick``
        # doesn't pin a big steady-state buffer; the recv loop calls back
        # for the next chunk in the same tick if the budget remains.
        # Mirrors chumicro_requests.HttpClient + chumicro_http_server
        # connection-state pattern.
        recv_scratch_size = min(recv_budget_per_tick, 512)
        self._recv_buffer = bytearray(recv_scratch_size)
        self._recv_view = memoryview(self._recv_buffer)

        self.state = WebSocketState.CONNECTING
        # Inbound frame parser; max_payload_bytes propagates from the
        # session-level message cap so the upstream cap also bounds heap
        # at the per-frame stage.
        self._frame_parser = FrameParser(max_payload_bytes=max_message_bytes)
        self._post_handshake_carry = b""

        self._tx_queue = _new_tx_queue(max_tx_queue_size + 8)
        self._tx_partial = None  # (bytes, offset) when last send was short.

        self._inbound_message_buffer = bytearray()
        self._inbound_message_opcode = None  # TEXT or BINARY when fragmented
        self._inbound_oversized = False
        # Running peer-reported size of the in-progress message.  Tracks
        # the sum of frame ``reported_length`` values across the message
        # — load-bearing when oversize trips at the frame layer (tier 3)
        # since the message buffer never receives those bytes.
        self._inbound_reported_length = 0
        self._inbound_empty_fragment_run = 0

        self._handshake_send_buffer = None
        self._handshake_send_offset = 0

        self._handshake_deadline_ticks = None
        self._close_deadline_ticks = None
        self._pending_ping_deadline_ticks = None

        self.last_close_code = None
        self.last_close_reason = ""
        self.last_error = None

        # Default callbacks fire as no-ops so subclasses + users can
        # store handlers unconditionally.
        self.on_text = _no_callback
        self.on_binary = _no_callback
        self.on_ping = _no_callback
        self.on_pong = _no_callback
        self.on_close = _no_callback
        self.on_oversized = _no_callback

    # -- public send / close ----------------------------------------------

    def send_text(self, text: str) -> None:
        """Enqueue a text frame.  Raises :class:`WebSocketStateError`
        if not OPEN, :class:`WebSocketBackpressureError` if TX is full.
        """
        if self.state != WebSocketState.OPEN:
            raise WebSocketStateError(
                f"send_text() requires OPEN state, was {self.state}",
            )
        self._enqueue_user_frame(OPCODE_TEXT, text.encode("utf-8"))

    def send_binary(self, data) -> None:
        """Enqueue a binary frame from ``bytes`` / ``bytearray`` /
        ``memoryview``.  Raises :class:`WebSocketStateError` if not
        OPEN, :class:`WebSocketBackpressureError` if TX is full.
        """
        if self.state != WebSocketState.OPEN:
            raise WebSocketStateError(
                f"send_binary() requires OPEN state, was {self.state}",
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
        """Send a PING (peer must echo as PONG per RFC 6455 §5.5.2).
        Manual :meth:`send_ping` is for application-level ping/pong.
        Payload is capped at 125 bytes (control-frame limit).
        """
        if self.state != WebSocketState.OPEN:
            raise WebSocketStateError(
                f"send_ping() requires OPEN state, was {self.state}",
            )
        self._enqueue_user_frame(OPCODE_PING, bytes(payload))
        self._arm_pong_deadline()

    def close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        """Initiate a graceful close handshake.  Raises
        :class:`WebSocketStateError` if already CLOSING/CLOSED.
        """
        if self.state in (WebSocketState.CLOSING, WebSocketState.CLOSED):
            raise WebSocketStateError(
                f"close() not allowed in state {self.state}",
            )
        self._send_close(code, reason, None)

    # -- subclass-customizable mask ---------------------------------------

    def _outbound_mask(self):  # pragma: no cover - abstract
        """Return the mask key for an outbound frame (or ``None``)."""
        raise NotImplementedError

    # -- handshake send (post-direction-specific setup) ------------------

    def _send_handshake_chunk(self, now_ms: int) -> None:
        """Push as much of the pending handshake bytes as the budget allows.

        On completion, defers to :meth:`_on_handshake_send_complete` which
        each subclass overrides to either advance to receiving (client) or
        transition to OPEN (server).
        """
        remaining = self._handshake_send_buffer[self._handshake_send_offset:]
        if not remaining:
            self._on_handshake_send_complete(now_ms)
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
        self._handshake_send_offset += sent
        if self._handshake_send_offset >= len(self._handshake_send_buffer):
            self._on_handshake_send_complete(now_ms)

    def _on_handshake_send_complete(self, now_ms: int) -> None:  # pragma: no cover - abstract
        """Called once the handshake send buffer drains."""
        raise NotImplementedError

    # -- enqueue ----------------------------------------------------------

    def _enqueue_user_frame(self, opcode: int, payload: bytes) -> None:
        """Encode + queue an outbound frame, enforcing the user-visible cap."""
        if len(self._tx_queue) >= self._max_tx_queue_size:
            raise WebSocketBackpressureError(
                f"TX queue is full ({self._max_tx_queue_size} messages); "
                f"call handle() to drain before sending more",
            )
        encoded = encode_frame(opcode, payload, fin=True, mask=self._outbound_mask())
        self._tx_queue.append(encoded)

    def _enqueue_internal_frame(self, opcode: int, payload: bytes) -> None:
        """Queue a system-driven frame (close, pong, auto-ping) — no cap check.

        Internal frames bypass ``max_tx_queue_size`` because the queue
        was sized for user payloads + headroom.  The deque's structural
        ``maxlen`` (= max_tx_queue_size + 8) bounds heap regardless.
        """
        encoded = encode_frame(opcode, payload, fin=True, mask=self._outbound_mask())
        self._tx_queue.append(encoded)

    # -- inbound drain (post-handshake) -----------------------------------

    def _drain_inbound(self, now_ms: int) -> None:
        """Read up to recv_budget bytes and feed the frame parser."""
        chunk = self._recv_chunk(self._recv_budget_per_tick)
        if chunk is None:
            return
        if not chunk:
            self._fail_with_error(
                WebSocketProtocolError(
                    "peer closed TCP without sending a CLOSE frame",
                ),
            )
            return
        self._feed_frame_bytes(chunk, now_ms)

    def _feed_frame_bytes(self, chunk: bytes, now_ms: int) -> None:
        """Push *chunk* through :class:`FrameParser`, handling completed frames."""
        offset = 0
        chunk_length = len(chunk)
        while offset < chunk_length:
            try:
                consumed = self._frame_parser.feed(chunk, offset)
            except WebSocketProtocolError as protocol_error:
                self._send_close(CLOSE_PROTOCOL_ERROR, str(protocol_error), now_ms)
                self.last_error = protocol_error
                return
            offset += consumed
            if self._frame_parser.state == FrameParseState.FRAME_READY:
                self._dispatch_frame(now_ms)
                if self.state == WebSocketState.CLOSED:
                    return
                self._frame_parser.reset()

    def _dispatch_frame(self, now_ms: int) -> None:
        """Route a just-completed frame through the message-level state
        machine.  Mask direction enforced per RFC 6455 §5.1.
        """
        opcode = self._frame_parser.opcode
        fin = self._frame_parser.fin
        had_mask = self._frame_parser.had_mask
        payload = self._frame_parser.payload

        if had_mask != self._inbound_mask_required:
            if self._inbound_mask_required:
                message = f"{self._role_label} frame must be masked"
            else:
                message = f"{self._role_label} frame must not be masked"
            self._send_close(CLOSE_PROTOCOL_ERROR, message, now_ms)
            return

        if opcode == OPCODE_CLOSE:
            self._handle_close_frame(payload, now_ms)
            return
        if opcode == OPCODE_PING:
            self._handle_ping_frame(payload)
            return
        if opcode == OPCODE_PONG:
            self._handle_pong_frame(payload)
            return
        # Reserved opcodes (0xB-0xF) are caught upstream by FrameParser.
        # Anything that gets here is a data opcode (TEXT, BINARY, or CONT).
        self._handle_data_frame(opcode, fin, payload, now_ms)

    def _handle_data_frame(self, opcode: int, fin: bool, payload: bytes, now_ms: int) -> None:
        """Reassemble fragmented messages, applying oversize policy."""
        frame_parser = self._frame_parser
        if opcode == OPCODE_CONTINUATION:
            if self._inbound_message_opcode is None:
                self._send_close(
                    CLOSE_PROTOCOL_ERROR,
                    "CONTINUATION frame with no in-progress message",
                    now_ms,
                )
                return
        else:
            # TEXT or BINARY — must NOT arrive mid-fragmentation.
            if self._inbound_message_opcode is not None:
                self._send_close(
                    CLOSE_PROTOCOL_ERROR,
                    f"new {opcode:#x} frame in the middle of a fragmented message",
                    now_ms,
                )
                return
            self._inbound_message_opcode = opcode
        self._inbound_reported_length += frame_parser.reported_length
        if frame_parser.reported_length > 0:
            self._inbound_empty_fragment_run = 0
        elif not fin:
            self._inbound_empty_fragment_run += 1
            if self._inbound_empty_fragment_run > _MAX_EMPTY_FRAGMENT_RUN:
                self._send_close(
                    CLOSE_PROTOCOL_ERROR,
                    "too many zero-length continuation frames",
                    now_ms,
                )
                return
        if frame_parser.oversized:
            # Tier 3: payload was drained at the frame layer, the empty
            # ``payload`` arg is by design.  Mark the message oversized
            # without extending the buffer.
            self._inbound_oversized = True
        else:
            self._extend_inbound_buffer(payload)

        if not fin:
            return

        if self._inbound_oversized:
            self._finish_oversized_message(now_ms)
            return

        message_opcode = self._inbound_message_opcode
        message_payload = bytes(self._inbound_message_buffer)
        self._reset_inbound_state()

        if message_opcode == OPCODE_TEXT:
            try:
                text = validate_text_payload(message_payload)
            except WebSocketProtocolError as utf8_error:
                self._send_close(CLOSE_BAD_DATA, str(utf8_error), now_ms)
                self.last_error = utf8_error
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

    def _finish_oversized_message(self, now_ms: int) -> None:
        """Apply the WhenOversized policy at message-FIN time.

        ``reported_length`` is the sum of declared frame lengths across
        the message — for message-level oversize this equals what the
        buffer would have held; for frame-level oversize (tier 3 at the
        FrameParser) the buffer is empty and only this counter carries
        the size peer reported.
        """
        reported_length = self._inbound_reported_length
        self._reset_inbound_state()
        policy = self._when_oversized
        if policy == WhenOversized.DROP_SILENT:
            return
        if policy == WhenOversized.DROP_WITH_EVENT:
            self.on_oversized(reported_length)
            return
        if policy == WhenOversized.DISCONNECT:
            self._send_close(
                CLOSE_TOO_BIG,
                f"message exceeded max_message_bytes={self._max_message_bytes}",
                now_ms,
            )

    def _reset_inbound_state(self) -> None:
        """Clear reassembly state for the next message."""
        self._inbound_message_buffer = bytearray()
        self._inbound_message_opcode = None
        self._inbound_oversized = False
        self._inbound_reported_length = 0
        self._inbound_empty_fragment_run = 0

    def _handle_close_frame(self, payload: bytes, now_ms: int) -> None:
        """Process inbound CLOSE — record + reciprocate or finalize."""
        try:
            code, reason = parse_close_payload(payload)
        except WebSocketProtocolError as parse_error:
            # Even close frames must be valid; respond with protocol error.
            self._send_close(CLOSE_PROTOCOL_ERROR, str(parse_error), now_ms)
            self.last_error = parse_error
            return

        if self.state == WebSocketState.CLOSING:
            # We initiated.  Peer's CLOSE finishes the handshake.
            if self.last_close_code is None:
                self.last_close_code = code
                self.last_close_reason = reason
            self._finalize_closed()
            return

        # Peer initiated.  Echo their close code back per RFC 6455 §5.5.1.
        self.last_close_code = code
        self.last_close_reason = reason
        self._send_close(code if code is not None else CLOSE_NORMAL, "", now_ms)
        self._finalize_closed()

    def _handle_ping_frame(self, payload: bytes) -> None:
        """Auto-pong inbound PING + fire user callback."""
        self._enqueue_internal_frame(OPCODE_PONG, payload)
        self.on_ping(payload)

    def _handle_pong_frame(self, payload: bytes) -> None:
        """Clear the pending-pong deadline and fire user callback."""
        self._pending_ping_deadline_ticks = None
        self.on_pong(payload)

    # -- outbound drain ---------------------------------------------------

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
        """Non-blocking recv; ``memoryview``, ``b""`` on EOF, or ``None`` on EAGAIN.

        Reads into the pre-allocated :attr:`_recv_buffer` and returns a
        ``memoryview`` window over the freshly-received bytes — zero copy
        on the recv path.  :class:`FrameParser` and the handshake parsers
        accept memoryview directly (``isinstance(chunk, memoryview)`` fast
        path in ``FrameParser.feed``) and copy bytes they keep into their
        own buffers before returning, so the view's lifetime ends with the
        caller's drain pass.  Returning ``bytes()`` instead would allocate
        per-recv and defeat the recv_into win.  Mirrors the zero-copy
        handoff in chumicro_requests.HttpClient._drive_recv +
        chumicro_http_server connection._drive_recv.
        """
        cap = min(max_bytes, len(self._recv_buffer))
        try:
            received = self._socket.recv_into(self._recv_view, cap)
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
        return self._recv_view[:received]

    # -- close + finalize -------------------------------------------------

    def _send_close(self, code: int, reason: str, now_ms: int | None) -> None:
        """Queue a CLOSE frame and transition to CLOSING.

        *now_ms* is the runner-supplied tick when this is reached from a
        ``handle()`` path; pass ``None`` from user-entry callers
        (``close()``) so the deadline gets a freshly-fetched base.

        Idempotent — a second :meth:`_send_close` while already CLOSING
        is a no-op (peer's CLOSE may arrive after we sent ours).
        """
        if self.state in (WebSocketState.CLOSING, WebSocketState.CLOSED):
            return
        try:
            payload = encode_close_payload(code, reason)
        except WebSocketProtocolError:
            # Reserved close code or oversize reason — fall back to a
            # no-body close so we still trigger the handshake.
            payload = b""
        self._enqueue_internal_frame(OPCODE_CLOSE, payload)
        # Only record close code + reason if not already set — preserves
        # the peer's values when this is the echo half of a peer-initiated
        # close handshake (where _handle_close_frame stored peer's
        # code/reason before calling us).
        if self.last_close_code is None:
            self.last_close_code = code
            self.last_close_reason = reason
        self.state = WebSocketState.CLOSING
        if now_ms is None:
            now_ms = self._ticks.ticks_ms()
        self._close_deadline_ticks = self._ticks.ticks_add(
            now_ms,
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
        self.state = WebSocketState.CLOSED
        self._close_deadline_ticks = None
        self._pending_ping_deadline_ticks = None
        self._on_finalized()
        code = self.last_close_code if self.last_close_code is not None else CLOSE_NORMAL
        self.on_close(code, self.last_close_reason)

    def _fail_with_error(self, error) -> None:
        """Record *error*, force close, transition to CLOSED, fire on_close."""
        if self.last_error is None:
            self.last_error = error
        if self.last_close_code is None:
            self.last_close_code = CLOSE_INTERNAL_ERROR
            self.last_close_reason = str(error)
        try:
            if self._socket is not None:
                self._socket.close()
        except Exception:  # noqa: BLE001 - best-effort
            pass
        self.state = WebSocketState.CLOSED
        self._close_deadline_ticks = None
        self._pending_ping_deadline_ticks = None
        self._on_finalized()
        self.on_close(self.last_close_code, self.last_close_reason)

    def _on_finalized(self) -> None:
        """Hook for subclasses to clear additional per-side state on close."""

    # -- timeouts ---------------------------------------------------------

    def _check_timeouts(self, now_ms: int) -> bool:
        """Trip an expired handshake / close / pong deadline.  Returns
        ``True`` if a deadline tripped (caller should yield the tick).
        """
        if (
            self._handshake_deadline_ticks is not None
            and self._ticks.ticks_diff(self._handshake_deadline_ticks, now_ms) <= 0
        ):
            self._fail_with_error(
                WebSocketTimeoutError(
                    f"handshake exceeded {self._handshake_timeout_ms} ms",
                ),
            )
            return True
        return self._check_close_and_pong_timeouts(now_ms)

    def _check_close_and_pong_timeouts(self, now_ms: int) -> bool:
        """Trip an expired close-deadline or pong-deadline.  Returns
        ``True`` if a deadline tripped (caller should yield the tick).
        """
        if (
            self._close_deadline_ticks is not None
            and self._ticks.ticks_diff(self._close_deadline_ticks, now_ms) <= 0
        ):
            # Force closed even though peer didn't echo CLOSE.
            self.last_error = WebSocketTimeoutError(
                f"peer did not send CLOSE within {self._close_timeout_ms} ms",
            )
            self._finalize_closed()
            return True
        if (
            self._pending_ping_deadline_ticks is not None
            and self._ticks.ticks_diff(self._pending_ping_deadline_ticks, now_ms) <= 0
        ):
            self._fail_with_error(
                WebSocketTimeoutError(
                    f"no PONG within {self._pong_timeout_ms} ms of last PING",
                ),
            )
            return True
        return False

    def _arm_pong_deadline(self, now_ms: int | None = None) -> None:
        """Set the pong-overdue watchdog if not already armed.

        When called from a ``handle()`` path, pass the runner-supplied
        *now_ms* so the deadline shares the tick.  User-entry callers
        (``send_ping``) run outside the tick loop and pass nothing.
        """
        if self._pong_timeout_ms is None:
            return
        if self._pending_ping_deadline_ticks is not None:
            return  # earlier ping still outstanding — keep its deadline
        if now_ms is None:
            now_ms = self._ticks.ticks_ms()
        self._pending_ping_deadline_ticks = self._ticks.ticks_add(
            now_ms,
            self._pong_timeout_ms,
        )
