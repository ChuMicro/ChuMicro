import errno
from collections import deque

from chumicro_websockets._wire import (
    CLOSE_BAD_DATA,
    CLOSE_INTERNAL_ERROR,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    CLOSE_TOO_BIG,
    DEFAULT_MAX_INBOUND_QUEUE_SIZE,
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

# Cap on zero-length continuation frames: an unbounded run is a liveness stall.
_MAX_EMPTY_FRAGMENT_RUN = 64

# Mirror chumicro_runner.IO_READ / IO_WRITE by value; literals avoid a runner dependency.
_IO_READ = 1
_IO_WRITE = 2


class WhenOversized:
    """Policy for inbound messages exceeding ``max_message_bytes``."""

    #: Drop the message silently; stay connected for the next one.
    DROP_SILENT = "drop_silent"

    #: Default. Drop the message, fire ``on_oversized(reported_length)``, and stay connected.
    DROP_WITH_EVENT = "drop_with_event"

    #: Close immediately with :data:`CLOSE_TOO_BIG` when oversize means peer corruption.
    DISCONNECT = "disconnect"


def _no_callback(*_args, **_kwargs):
    return None


def _new_tx_queue(maxlen):
    # MicroPython/CircuitPython deque takes a flags arg; CPython's does not.
    try:
        return deque((), maxlen, 1)
    except TypeError:
        return deque((), maxlen)


def _force_non_blocking(socket):
    # MicroPython sockets start blocking; the tick-based RX path needs non-blocking recv_into.
    setblocking = getattr(socket, "setblocking", None)
    if setblocking is None:
        return
    try:
        setblocking(False)
    except OSError:  # pragma: no cover - defensive
        pass


class InboundMessage:
    """A complete inbound WebSocket data message returned by ``next_message``."""

    def __init__(self, *, is_text: bool, text: str | None = None, data: bytes | None = None):
        self.is_text = is_text
        self.text = text
        self.data = data

    def __repr__(self):
        if self.is_text:
            return f"InboundMessage(text={self.text!r})"
        return f"InboundMessage(data={len(self.data)} bytes)"


class _InboundWait:
    # io_socket is None because the session already owns the socket's poll interest.

    io_socket = None


_INBOUND_WAIT = _InboundWait()


class _BaseSession:
    _peer_label: str = ""
    _inbound_mask_required: bool = False

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
        max_inbound_queue_size: int = DEFAULT_MAX_INBOUND_QUEUE_SIZE,
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
        self._max_inbound_queue_size = max_inbound_queue_size

        self._ticks = ticks

        # Pre-allocated recv scratch, reused each tick to avoid heap churn; capped at 512 B.
        recv_scratch_size = min(recv_budget_per_tick, 512)
        self._recv_buffer = bytearray(recv_scratch_size)
        self._recv_view = memoryview(self._recv_buffer)

        self.state = WebSocketState.CONNECTING
        self._frame_parser = FrameParser(max_payload_bytes=max_message_bytes)
        self._post_handshake_carry = b""

        self._tx_queue = _new_tx_queue(max_tx_queue_size + 8)
        # Internal frames check this bound explicitly: deque overflow differs across runtimes.
        self._tx_queue_hard_cap = max_tx_queue_size + 8
        self._tx_partial = None  # (buffer, offset) when a send was short

        self._inbound_message_buffer = bytearray()
        self._inbound_message_opcode = None  # TEXT or BINARY when fragmented
        self._inbound_oversized = False
        self._inbound_queue = None
        self._inbound_to_queue = False
        # Peer-reported size of the in-progress message; load-bearing on tier-3 oversize.
        self._inbound_reported_length = 0
        self._inbound_empty_fragment_run = 0

        self._handshake_send_buffer = None
        # memoryview over _handshake_send_buffer for zero-copy per-tick send slices.
        self._handshake_send_view = None
        self._handshake_send_offset = 0

        self._handshake_deadline_ticks = None
        self._close_deadline_ticks = None
        self._pending_ping_deadline_ticks = None
        self._next_auto_ping_ticks = None

        self.last_close_code = None
        self.last_close_reason = ""
        self.last_error = None

        # No-op defaults let the session call callbacks without a None check.
        self.on_text = _no_callback
        self.on_binary = _no_callback
        self.on_ping = _no_callback
        self.on_pong = _no_callback
        self.on_close = _no_callback
        self.on_oversized = _no_callback

    @property
    def io_socket(self):
        """The session's socket-ish object while live, else ``None``."""
        if self._socket is None:
            return None
        if self.state == WebSocketState.CLOSED:
            return None
        return self._socket

    def io_interest(self, now_ms):
        """Poll-interest bitmask (``_IO_READ`` / ``_IO_WRITE``) for the runner."""
        if self.state in (WebSocketState.OPEN, WebSocketState.CLOSING):
            interest = _IO_READ
            if bool(self._tx_queue) or self._tx_partial is not None:
                interest |= _IO_WRITE
            return interest
        if self.state == WebSocketState.CONNECTING:
            interest = 0
            if self._connecting_wants_read(now_ms):
                interest |= _IO_READ
            if self._connecting_wants_write(now_ms):
                interest |= _IO_WRITE
            return interest
        return 0

    def _connecting_wants_read(self, now_ms) -> bool:  # noqa: ARG002 - runner contract
        return False

    def _connecting_wants_write(self, now_ms) -> bool:  # noqa: ARG002 - runner contract
        return False

    def next_deadline(self, now_ms):  # noqa: ARG002 - runner contract
        """Earliest tick at which ``handle()`` must run on a quiet socket, or ``None``."""
        ticks_diff = self._ticks.ticks_diff
        nearest = None
        for candidate in (
            self._handshake_deadline_ticks,
            self._close_deadline_ticks,
            self._pending_ping_deadline_ticks,
            self._next_auto_ping_ticks,
        ):
            if candidate is None:
                continue
            if nearest is None or ticks_diff(candidate, nearest) < 0:
                nearest = candidate
        return nearest

    def send_text(self, text: str) -> None:
        """Enqueue a text frame.

        Raises:
            WebSocketStateError: Not in OPEN state.
            WebSocketBackpressureError: TX queue is full.
        """
        if self.state != WebSocketState.OPEN:
            raise WebSocketStateError(
                f"send_text() requires OPEN state, was {self.state}",
            )
        self._enqueue_user_frame(OPCODE_TEXT, text.encode("utf-8"))

    def send_binary(self, data) -> None:
        """Enqueue a binary frame from ``bytes``, ``bytearray``, or ``memoryview``.

        Raises:
            WebSocketStateError: Not in OPEN state.
            WebSocketBackpressureError: TX queue is full.
        """
        if self.state != WebSocketState.OPEN:
            raise WebSocketStateError(
                f"send_binary() requires OPEN state, was {self.state}",
            )
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(
                f"send_binary() requires bytes, bytearray, or memoryview; "
                f"got {type(data).__name__}",
            )
        # No defensive copy: the frame is encoded synchronously before this returns.
        self._enqueue_user_frame(OPCODE_BINARY, data)

    def send_ping(self, payload: bytes = b"") -> None:
        """Send a PING frame the peer must echo as a PONG; payload capped at 125 bytes."""
        if self.state != WebSocketState.OPEN:
            raise WebSocketStateError(
                f"send_ping() requires OPEN state, was {self.state}",
            )
        self._enqueue_user_frame(OPCODE_PING, bytes(payload))
        self._arm_pong_deadline()

    def close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        """Initiate a graceful close handshake.

        Raises:
            WebSocketStateError: Already CLOSING or CLOSED.
        """
        if self.state in (WebSocketState.CLOSING, WebSocketState.CLOSED):
            raise WebSocketStateError(
                f"close() not allowed in state {self.state}",
            )
        self._send_close(code, reason, None)

    def next_message(self):
        """Suspend until the next inbound data message, then return it.

        Returns:
            The next :class:`InboundMessage`, or ``None`` once the session is CLOSED and drained.
        """
        if self._inbound_queue is None:
            # 2-arg deque drops the oldest item on append-when-full on every runtime.
            self._inbound_queue = deque((), self._max_inbound_queue_size)
            self._inbound_to_queue = True
        while True:
            if self._inbound_queue:
                return self._inbound_queue.popleft()
            if self.state == WebSocketState.CLOSED:
                return None
            yield _INBOUND_WAIT

    def _outbound_mask(self):  # pragma: no cover - abstract
        raise NotImplementedError

    def _send_handshake_chunk(self, now_ms: int) -> None:
        remaining = self._handshake_send_view[self._handshake_send_offset:]
        if not remaining:
            self._on_handshake_send_complete(now_ms)
            return
        chunk = remaining[: self._send_budget_per_tick]
        try:
            sent = self._socket.send(chunk)
        except OSError as send_error:
            if send_error.errno == errno.EAGAIN:
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
        raise NotImplementedError

    def _enqueue_user_frame(self, opcode: int, payload: bytes) -> None:
        if len(self._tx_queue) >= self._max_tx_queue_size:
            raise WebSocketBackpressureError(
                f"TX queue is full ({self._max_tx_queue_size} messages); "
                f"call handle() to drain before sending more",
            )
        encoded = encode_frame(opcode, payload, fin=True, mask=self._outbound_mask())
        self._tx_queue.append(encoded)

    def _enqueue_internal_frame(self, opcode: int, payload: bytes) -> None:
        # Reserve one headroom slot for CLOSE: non-CLOSE internal frames stop one short.
        limit = self._tx_queue_hard_cap
        if opcode != OPCODE_CLOSE:
            limit -= 1
        if len(self._tx_queue) >= limit:
            return
        encoded = encode_frame(opcode, payload, fin=True, mask=self._outbound_mask())
        self._tx_queue.append(encoded)

    def _drain_inbound(self, now_ms: int) -> None:
        remaining = self._recv_budget_per_tick
        while remaining > 0:
            chunk = self._recv_chunk(remaining)
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
            if self.state == WebSocketState.CLOSED:
                return
            remaining -= len(chunk)

    def _feed_frame_bytes(self, chunk: bytes, now_ms: int) -> None:
        # A parser latched in ERROR consumes nothing; feeding it would spin forever.
        if self._frame_parser.state == FrameParseState.ERROR:
            return
        offset = 0
        chunk_length = len(chunk)
        while offset < chunk_length:
            try:
                consumed = self._frame_parser.feed(chunk, offset)
            except WebSocketProtocolError as protocol_error:
                self._send_close(CLOSE_PROTOCOL_ERROR, str(protocol_error), now_ms)
                self.last_error = protocol_error
                return
            if consumed == 0:
                # Zero progress with bytes left means a terminal state; stop rather than spin.
                return
            offset += consumed
            if self._frame_parser.state == FrameParseState.FRAME_READY:
                try:
                    self._dispatch_frame(now_ms)
                finally:
                    # Reset even if a callback raised; skip once CLOSED, where finalize needs the fields.
                    if self.state != WebSocketState.CLOSED:
                        self._frame_parser.reset()
                if self.state == WebSocketState.CLOSED:
                    return

    def _dispatch_frame(self, now_ms: int) -> None:
        opcode = self._frame_parser.opcode
        fin = self._frame_parser.fin
        had_mask = self._frame_parser.had_mask
        payload = self._frame_parser.payload

        if had_mask != self._inbound_mask_required:
            if self._inbound_mask_required:
                message = f"{self._peer_label} frame must be masked"
            else:
                message = f"{self._peer_label} frame must not be masked"
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
        # Reserved opcodes are rejected upstream by FrameParser; this is a data opcode.
        self._handle_data_frame(opcode, fin, payload, now_ms)

    def _handle_data_frame(self, opcode: int, fin: bool, payload: bytes, now_ms: int) -> None:
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
            # TEXT or BINARY must not arrive mid-fragmentation.
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
            # Tier 3: payload was drained at the frame layer; mark oversized, don't buffer.
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
            if self._inbound_to_queue:
                self._inbound_queue.append(InboundMessage(is_text=True, text=text))
            else:
                self.on_text(text)
        elif self._inbound_to_queue:
            self._inbound_queue.append(InboundMessage(is_text=False, data=message_payload))
        else:
            self.on_binary(message_payload)

    def _extend_inbound_buffer(self, payload: bytes) -> None:
        if self._inbound_oversized:
            return  # already oversized; wait for FIN
        projected = len(self._inbound_message_buffer) + len(payload)
        if projected > self._max_message_bytes:
            self._inbound_oversized = True
            return
        self._inbound_message_buffer.extend(payload)

    def _finish_oversized_message(self, now_ms: int) -> None:
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
        self._inbound_message_buffer = bytearray()
        self._inbound_message_opcode = None
        self._inbound_oversized = False
        self._inbound_reported_length = 0
        self._inbound_empty_fragment_run = 0

    def _handle_close_frame(self, payload: bytes, now_ms: int) -> None:
        try:
            code, reason = parse_close_payload(payload)
        except WebSocketProtocolError as parse_error:
            self._send_close(CLOSE_PROTOCOL_ERROR, str(parse_error), now_ms)
            self.last_error = parse_error
            return

        if self.state == WebSocketState.CLOSING:
            if self.last_close_code is None:
                self.last_close_code = code
                self.last_close_reason = reason
            self._finalize_closed()
            return

        # Peer initiated: echo the close code back (RFC 6455 §5.5.1).
        self.last_close_code = code
        self.last_close_reason = reason
        self._send_close(code if code is not None else CLOSE_NORMAL, "", now_ms)
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
                # memoryview so each send slices the unsent tail without copying.
                self._tx_partial = (memoryview(self._tx_queue.popleft()), 0)
            buffer, offset = self._tx_partial
            chunk = buffer[offset : offset + budget]
            try:
                sent = self._socket.send(chunk)
            except OSError as send_error:
                if send_error.errno == errno.EAGAIN:
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
        cap = min(max_bytes, len(self._recv_buffer))
        try:
            received = self._socket.recv_into(self._recv_view, cap)
        except OSError as recv_error:
            if recv_error.errno == errno.EAGAIN:
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

    def _send_close(self, code: int, reason: str, now_ms: int | None) -> None:
        if self.state in (WebSocketState.CLOSING, WebSocketState.CLOSED):
            return
        try:
            payload = encode_close_payload(code, reason)
        except WebSocketProtocolError:
            # Reserved code or oversize reason: fall back to a no-body close.
            payload = b""
        self._enqueue_internal_frame(OPCODE_CLOSE, payload)
        # Record only if unset, preserving the peer's values on an echoed close.
        if self.last_close_code is None:
            self.last_close_code = code
            self.last_close_reason = reason
        self.state = WebSocketState.CLOSING
        if now_ms is None:
            # close() runs outside a tick; fetch a time base.
            now_ms = self._ticks.ticks_ms()
        self._close_deadline_ticks = self._ticks.ticks_add(
            now_ms,
            self._close_timeout_ms,
        )

    def _finalize_closed(self) -> None:
        # Flush the CLOSE frame so the peer sees our reply before we drop TCP.
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

    def _check_timeouts(self, now_ms: int) -> bool:
        ticks_diff = self._ticks.ticks_diff
        if (
            self._handshake_deadline_ticks is not None
            and ticks_diff(self._handshake_deadline_ticks, now_ms) <= 0
        ):
            self._fail_with_error(
                WebSocketTimeoutError(
                    f"handshake exceeded {self._handshake_timeout_ms} ms",
                ),
            )
            return True
        if (
            self._close_deadline_ticks is not None
            and ticks_diff(self._close_deadline_ticks, now_ms) <= 0
        ):
            self.last_error = WebSocketTimeoutError(
                f"peer did not send CLOSE within {self._close_timeout_ms} ms",
            )
            self._finalize_closed()
            return True
        if (
            self._pending_ping_deadline_ticks is not None
            and ticks_diff(self._pending_ping_deadline_ticks, now_ms) <= 0
        ):
            self._fail_with_error(
                WebSocketTimeoutError(
                    f"no PONG within {self._pong_timeout_ms} ms of last PING",
                ),
            )
            return True
        return False

    def _arm_pong_deadline(self, now_ms: int | None = None) -> None:
        if self._pong_timeout_ms is None:
            return
        if self._pending_ping_deadline_ticks is not None:
            return  # keep the earliest outstanding ping's deadline
        if now_ms is None:
            # send_ping() runs outside a tick; fetch a time base.
            now_ms = self._ticks.ticks_ms()
        self._pending_ping_deadline_ticks = self._ticks.ticks_add(
            now_ms,
            self._pong_timeout_ms,
        )
