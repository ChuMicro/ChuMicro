"""MQTT 3.1.1 client built on chumicro-sockets + chumicro-timing.

Entry point :class:`MQTTClient` exposes the runner-shaped contract
from Decision 0014 — :meth:`check(now_ms) -> bool` reports whether
work is pending; :meth:`handle(now_ms)` performs one tick's worth
of progress.  No threads, no async — cooperative dispatch in the
caller's tick loop.

What this rewrites from the pythonProject3 client (Decision 0029
Phase 6):

* QoS 1 in-flight tracking → :class:`InFlightTable` keyed by
  packet_id.  Multiple concurrent QoS 1 publishes work correctly.
* State machine → explicit :class:`ProtocolState` ladder + per-
  pending-response :class:`PendingResponse` entries.  No more
  blanket ``_waiting_state`` lock that prevented unrelated work.
* Callback dispatch → callbacks live on the in-flight entries
  themselves.  PUBACK matching looks up by packet_id rather than
  popping from a deque.
* Socket layer → injected :class:`TCPClientSocket` (typically built
  via ``chumicro_sockets.tcp_client_socket`` /
  ``tls_client_socket``).  No ``adafruit_connection_manager``
  dependency; downstream tests inject ``FakeSocket``.
* Timer layer → :func:`chumicro_timing.ticks_ms` /
  :func:`ticks_diff` / :func:`ticks_add`, swapping out
  ``adafruit_ticks``.

What's preserved from the original:

* Wire-format primitives (encode_varlen / decode_varlen /
  encode_string / topic_matches) — these were solid; pulled into
  :mod:`chumicro_mqtt._packets` mostly verbatim.
* Pre-allocated 256 B steady-state RX buffer with a degraded
  oversize-message path.
* Callback registration shape (on_message / on_connect / on_publish
  / etc.); pattern-routed message handlers list.
* Will + retain.
* PINGREQ at half the keepalive interval.
"""

from chumicro_timing import ticks_add, ticks_diff, ticks_ms

from chumicro_mqtt._decoder import (
    PacketDecoder,
    ParsedAck,
    ParsedPublish,
    _OversizedMessage,
)
from chumicro_mqtt._encoder import (
    encode_connect,
    encode_puback,
    encode_publish,
    encode_subscribe,
    encode_unsubscribe,
)
from chumicro_mqtt._errors import (
    MQTTConnectError,
    MQTTError,
    MQTTProtocolError,
)
from chumicro_mqtt._packets import (
    PACKET_CONNACK,
    PACKET_PINGREQ,
    PACKET_PINGRESP,
    PACKET_PUBACK,
    PACKET_SUBACK,
    PACKET_UNSUBACK,
    topic_matches,
)
from chumicro_mqtt._state import (
    Awaiting,
    InFlightPublish,
    InFlightTable,
    PendingResponse,
    ProtocolState,
)

# ---------------------------------------------------------------------------
# WhenOversized policy — Decision 0029 Phase 6 §"Oversized-message policy"
# ---------------------------------------------------------------------------


class WhenOversized:
    """Policy for inbound PUBLISH whose payload exceeds ``max_message_size``."""

    #: Drop silently; PUBACK the broker.  Original behaviour.
    DROP_SILENT = "drop_silent"

    #: Default.  Drop the payload, fire ``on_oversized(topic, reported_length)``,
    #: still PUBACK so the broker doesn't retransmit.
    DROP_WITH_EVENT = "drop_with_event"

    #: Treat as a protocol error: disconnect.  Use when application
    #: invariants assume payloads fit within the configured cap.
    DISCONNECT = "disconnect"


def _no_callback(*_args, **_kwargs):
    """Default callback that does nothing.  Lets handlers be stored
    unconditionally — the dispatch loop never branches on None."""
    return None


# ---------------------------------------------------------------------------
# MQTTClient
# ---------------------------------------------------------------------------


class MQTTClient:
    """Non-blocking MQTT 3.1.1 client (QoS 0 + 1).

    Construct with an already-connected :class:`TCPClientSocket` and
    user knobs; then drive via :meth:`check` / :meth:`handle` from a
    runner tick or a hand-rolled loop.  All callbacks fire from
    :meth:`handle` — never from a thread or interrupt.
    """

    def __init__(
        self,
        socket,
        *,
        client_id,
        keep_alive_seconds=60,
        ack_timeout_seconds=5.0,
        publish_retry_max=3,
        username=None,
        password=None,
        clean_session=True,
        will_topic=None,
        will_message=None,
        will_qos=0,
        will_retain=False,
        rx_buffer_size=None,
        max_message_size=None,
        when_oversized=WhenOversized.DROP_WITH_EVENT,
        ticks_ms_func=ticks_ms,
        ticks_add_func=ticks_add,
        ticks_diff_func=ticks_diff,
    ):
        """Wire up the client.

        Args:
            socket: An already-connected :class:`TCPClientSocket`
                (typically from ``chumicro_sockets.tcp_client_socket``
                or ``tls_client_socket``).  The client takes ownership;
                :meth:`disconnect` closes it.
            client_id: MQTT client identifier — must be unique per
                broker.
            keep_alive_seconds: Broker idle timeout.  PINGREQ runs at
                half this interval client-side.
            ack_timeout_seconds: Per-PUBACK / SUBACK / etc. deadline.
                Triggers a retry (PUBLISH) or fault (everything else).
            publish_retry_max: Max QoS 1 PUBLISH retries before giving
                up + transitioning to FAILED.
            username / password: Optional auth.
            clean_session: ``True`` (default) drops persistent session
                state on connect; ``False`` resumes for QoS 1+
                retransmit-across-reconnects.
            will_topic / will_message / will_qos / will_retain: "Last
                will" — broker publishes on uncleaning disconnect.
            rx_buffer_size: Steady-state RX buffer size.  Defaults
                to 256 (matches the original client).
            max_message_size: Cap on a single inbound PUBLISH payload.
                Defaults to 256 KB.
            when_oversized: Policy for messages above the cap.
                See :class:`WhenOversized`.
            ticks_ms_func / ticks_add_func / ticks_diff_func: Inject
                fakes for testing.  Default to ``chumicro_timing``.
        """
        self._socket = socket
        self._client_id = client_id
        self._keep_alive_seconds = keep_alive_seconds
        self._ack_timeout_ms = int(ack_timeout_seconds * 1000)
        self._publish_retry_max = publish_retry_max
        self._username = username
        self._password = password
        self._clean_session = clean_session
        self._will_topic = will_topic
        self._will_message = will_message
        self._will_qos = will_qos
        self._will_retain = will_retain
        self._when_oversized = when_oversized

        self._ticks_ms = ticks_ms_func
        self._ticks_add = ticks_add_func
        self._ticks_diff = ticks_diff_func

        decoder_kwargs = {}
        if rx_buffer_size is not None:
            decoder_kwargs["rx_buffer_size"] = rx_buffer_size
        if max_message_size is not None:
            decoder_kwargs["max_message_size"] = max_message_size
        self._decoder = PacketDecoder(**decoder_kwargs)

        # State.
        self._state = ProtocolState.DISCONNECTED
        self._in_flight = InFlightTable()
        self._pending_responses = []
        self._tx_queue = []  # Backpressure-safe outbound queue.
        self._partial_send = None  # (bytes, offset) when last send was short.

        # Keepalive bookkeeping.
        self._next_ping_due_ticks = 0
        self._ping_interval_ms = max(1000, keep_alive_seconds * 1000 // 2)

        # Callbacks (default no-ops so handlers can call without branching).
        self.on_message = _no_callback
        self.on_connect = _no_callback
        self.on_disconnect = _no_callback
        self.on_subscribe = _no_callback
        self.on_unsubscribe = _no_callback
        self.on_publish = _no_callback
        self.on_oversized = _no_callback
        self._pattern_handlers = []
        self._last_error = None

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    @property
    def state(self):
        """Current :class:`ProtocolState` value."""
        return self._state

    @property
    def last_error(self):
        """Last :class:`MQTTError` seen on this connection (or ``None``)."""
        return self._last_error

    def connect(self):
        """Queue a CONNECT packet and transition to CONNECTING.

        The actual handshake completes on subsequent :meth:`handle`
        ticks — :meth:`connect` is non-blocking.  Callers either
        loop ``while client.state in {DISCONNECTED, CONNECTING}: handle()``
        or run under a Runner that does.

        Raises:
            MQTTError: When called in a non-DISCONNECTED state.
        """
        if self._state != ProtocolState.DISCONNECTED:
            raise MQTTError(
                f"connect() requires DISCONNECTED state, was {self._state}",
            )
        packet = encode_connect(
            client_id=self._client_id,
            keep_alive_seconds=self._keep_alive_seconds,
            clean_session=self._clean_session,
            username=self._username,
            password=self._password,
            will_topic=self._will_topic,
            will_message=self._will_message,
            will_qos=self._will_qos,
            will_retain=self._will_retain,
        )
        self._tx_queue.append(packet)
        self._pending_responses.append(
            PendingResponse(
                awaiting=Awaiting.CONNACK,
                deadline_ticks=self._deadline(self._ack_timeout_ms),
            ),
        )
        self._state = ProtocolState.CONNECTING

    def disconnect(self):
        """Queue a DISCONNECT packet, close the socket, mark DISCONNECTED.

        Best-effort: tries to send DISCONNECT and close cleanly, but
        any exception during send/close is swallowed — the goal is
        to leave the client in a known-good DISCONNECTED state on
        return.
        """
        # Send DISCONNECT directly (skip the queue — we're tearing
        # down).  Errors are swallowed: the broker will time us out
        # if the socket is already broken.
        try:
            self._send_raw(b"\xe0\x00")
        except Exception:  # noqa: BLE001 — disconnect is best-effort  # pragma: no cover - defensive
            pass
        try:
            self._socket.close()
        except Exception:  # noqa: BLE001 — disconnect is best-effort  # pragma: no cover - defensive
            pass
        self._state = ProtocolState.DISCONNECTED
        self.on_disconnect()

    # ------------------------------------------------------------------
    # Public publish / subscribe / unsubscribe
    # ------------------------------------------------------------------

    def publish(self, topic, payload, *, qos=0, retain=False, on_publish=None):
        """Queue a PUBLISH packet.

        For QoS 0, the packet is queued and considered "delivered"
        as soon as it reaches the wire (the optional *on_publish*
        callback fires from the next :meth:`handle` once the bytes
        are sent).

        For QoS 1, an in-flight entry is opened with the packet's
        bytes + the callback; PUBACK matches on packet_id and fires
        the callback exactly once.  Retries up to *publish_retry_max*
        on ack timeout.

        Args:
            topic: Publish topic.
            payload: ``bytes`` / ``str``.  ``str`` is auto-encoded as UTF-8.
            qos: 0 or 1.  QoS 2 raises :class:`UnsupportedQoSError`.
            retain: True for retained messages.
            on_publish: Optional callback fired on successful delivery
                (after PUBACK for QoS 1, after wire-write for QoS 0).
                Signature: ``on_publish(topic, payload_bytes)``.

        Raises:
            MQTTError: Client not in CONNECTED state.
        """
        if self._state != ProtocolState.CONNECTED:
            raise MQTTError(
                f"publish() requires CONNECTED state, was {self._state}",
            )
        if qos > 1:
            from chumicro_mqtt._errors import UnsupportedQoSError  # noqa: PLC0415

            raise UnsupportedQoSError(
                "qos must be 0 or 1; QoS 2 is reserved-not-implemented",
            )
        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = bytes(payload)  # pragma: no cover - bytes-passthrough trivial path

        if qos == 0:
            packet = encode_publish(
                topic=topic, payload=payload_bytes, qos=0, retain=retain,
            )
            self._tx_queue.append(packet)
            # QoS 0 has no ack — fire the callback once the bytes hit the wire.
            if on_publish is not None:
                self._tx_queue.append(("__qos0_callback__", on_publish, topic, payload_bytes))
            return

        # QoS 1: allocate packet_id, encode, queue, register in-flight.
        packet_id = self._in_flight.allocate_id()
        packet = encode_publish(
            topic=topic,
            payload=payload_bytes,
            qos=1,
            retain=retain,
            packet_id=packet_id,
        )

        def _wrapped_callback():
            if on_publish is not None:
                on_publish(topic, payload_bytes)
            self.on_publish(topic, payload_bytes)

        entry = InFlightPublish(
            packet_id=packet_id,
            packet_bytes=packet,
            deadline_ticks=self._deadline(self._ack_timeout_ms),
            callback=_wrapped_callback,
        )
        self._in_flight.add(entry)
        self._tx_queue.append(packet)

    def subscribe(self, topic, qos=0, *, on_subscribe=None):
        """Queue a SUBSCRIBE for *topic*.

        Args:
            topic: Topic filter (may include ``+`` / ``#`` wildcards).
            qos: 0 or 1.
            on_subscribe: Optional callback fired on SUBACK.
                Signature: ``on_subscribe(topic, granted_qos)``.

        Raises:
            MQTTError: Client not in CONNECTED state.
        """
        if self._state != ProtocolState.CONNECTED:
            raise MQTTError(
                f"subscribe() requires CONNECTED state, was {self._state}",
            )
        packet_id = self._in_flight.allocate_id()  # Reuse the id pool.
        packet = encode_subscribe(
            packet_id=packet_id, subscriptions=[(topic, qos)],
        )
        self._tx_queue.append(packet)

        def _wrapped(granted_qos):
            if on_subscribe is not None:
                on_subscribe(topic, granted_qos)
            self.on_subscribe(topic, granted_qos)

        self._pending_responses.append(
            PendingResponse(
                awaiting=Awaiting.SUBACK,
                deadline_ticks=self._deadline(self._ack_timeout_ms),
                packet_id=packet_id,
                callback=_wrapped,
            ),
        )

    def unsubscribe(self, topic, *, on_unsubscribe=None):
        """Queue an UNSUBSCRIBE for *topic*."""
        if self._state != ProtocolState.CONNECTED:
            raise MQTTError(
                f"unsubscribe() requires CONNECTED state, was {self._state}",
            )
        packet_id = self._in_flight.allocate_id()
        packet = encode_unsubscribe(packet_id=packet_id, topics=[topic])
        self._tx_queue.append(packet)

        def _wrapped():
            if on_unsubscribe is not None:
                on_unsubscribe(topic)
            self.on_unsubscribe(topic)

        self._pending_responses.append(
            PendingResponse(
                awaiting=Awaiting.UNSUBACK,
                deadline_ticks=self._deadline(self._ack_timeout_ms),
                packet_id=packet_id,
                callback=_wrapped,
            ),
        )

    def add_pattern_handler(self, pattern, handler):
        """Register *handler* for inbound messages matching *pattern*.

        The handler signature is ``handler(topic, payload_bytes)``.
        Multiple patterns can be registered; matching is via
        :func:`chumicro_mqtt._packets.topic_matches`.
        """
        self._pattern_handlers.append((pattern, handler))

    # ------------------------------------------------------------------
    # Runner contract — Decision 0014
    # ------------------------------------------------------------------

    def check(self, now_ms):  # noqa: ARG002 — runner contract uses now_ms
        """Return ``True`` if there's outbound work or readable bytes."""
        if self._state in (ProtocolState.DISCONNECTED, ProtocolState.FAILED):
            return False
        return bool(self._tx_queue) or self._socket_readable()

    def handle(self, now_ms):
        """One tick of progress.

        Drains the TX queue first (sends as many packets as the
        socket accepts), then pulls inbound bytes into the decoder
        and processes any complete packets, then checks ack
        deadlines + keepalive timer.
        """
        if self._state in (ProtocolState.DISCONNECTED, ProtocolState.FAILED):
            return
        try:
            self._drain_tx_queue()
            self._read_inbound()
            self._check_deadlines(now_ms)
            self._check_keepalive(now_ms)
            # Drain again — _check_deadlines may have enqueued
            # PUBLISH retries and _check_keepalive may have enqueued
            # PINGREQ.  Without this, those packets sit in the queue
            # for an extra tick before reaching the wire.
            self._drain_tx_queue()
        except MQTTError as error:
            self._last_error = error
            self._state = ProtocolState.FAILED
        except OSError as error:
            self._last_error = MQTTError(f"socket error: {error}")
            self._state = ProtocolState.FAILED

    # ------------------------------------------------------------------
    # Internal — TX path
    # ------------------------------------------------------------------

    def _drain_tx_queue(self):
        """Send queued packets until the socket would block.

        Each item in the queue is either ``bytes`` (a packet) or a
        ``("__qos0_callback__", callback, topic, payload)`` tuple
        (a deferred QoS 0 on_publish hook).
        """
        # Resume a previous partial send first.
        if self._partial_send is not None:  # pragma: no cover - rare partial-send recovery path
            packet, offset = self._partial_send
            sent = self._send_raw(packet[offset:])
            new_offset = offset + sent
            if new_offset >= len(packet):
                self._partial_send = None
            else:
                self._partial_send = (packet, new_offset)
                return  # Socket would block — try again next tick.

        while self._tx_queue:
            head = self._tx_queue[0]
            if isinstance(head, tuple) and head[0] == "__qos0_callback__":
                _, callback, topic, payload = head
                self._tx_queue.pop(0)
                callback(topic, payload)
                self.on_publish(topic, payload)
                continue
            packet = head
            sent = self._send_raw(packet)
            if sent <= 0:  # pragma: no cover - non-blocking-EAGAIN backpressure path
                # Socket would block — wait for next tick.
                return
            if sent < len(packet):  # pragma: no cover - rare partial-send path
                self._partial_send = (packet, sent)
                self._tx_queue.pop(0)
                return
            self._tx_queue.pop(0)

    def _send_raw(self, payload):
        """Send *payload*; return bytes sent (may be 0 on EAGAIN)."""
        try:
            return self._socket.send(payload)
        except OSError as error:
            errno = error.args[0] if error.args else None
            if errno in (11, 35):  # pragma: no cover - EAGAIN handling
                return 0
            raise

    # ------------------------------------------------------------------
    # Internal — RX path
    # ------------------------------------------------------------------

    def _socket_readable(self):
        """Heuristic: is there inbound work?  Always optimistic — the
        actual recv may still raise EAGAIN, which we handle.

        Returns ``True`` so :meth:`handle` always tries to read.  A
        smarter implementation would use the socket's poll fd, but
        the cooperative tick model already guarantees we revisit
        every tick — calling recv every tick is cheap when there's
        nothing to read.
        """
        return True

    def _read_inbound(self):
        """Pull bytes off the socket into the decoder; process complete packets.

        The loop pulls bytes until ``recv_into`` reports zero (EAGAIN
        on non-blocking sockets / clean peer close) — never short-
        circuits on "got < capacity" because TCP can fragment a
        single broker burst across multiple recv calls.  The pull-
        loop is still bounded: the decoder's capacity caps how many
        bytes one tick consumes (default 256 B steady-state buffer),
        and the surrounding tick-runner ensures handle() returns
        promptly.
        """
        while True:
            buffer_view = self._decoder.fill_buffer()
            capacity = self._decoder.fill_capacity()
            if capacity <= 0:
                # Buffer full — process what we have, then refill.
                break  # pragma: no cover - oversized-message path
            try:
                got = self._socket.recv_into(buffer_view, capacity)
            except OSError as error:
                errno = error.args[0] if error.args else None
                if errno in (11, 35):  # pragma: no cover - EAGAIN handling
                    break  # EAGAIN — no data this tick.
                raise
            if got == 0:
                break  # Peer closed or no data this tick.
            self._decoder.advance(got)

        # Now process complete packets.
        while True:
            packet = self._decoder.read_next()
            if packet is None:
                break
            self._dispatch(packet)

    def _dispatch(self, packet):
        """Route a parsed packet to the right handler."""
        if isinstance(packet, ParsedPublish):
            self._handle_inbound_publish(packet)
            return
        if isinstance(packet, _OversizedMessage):
            self._handle_oversized(packet)
            return
        if isinstance(packet, ParsedAck):
            self._handle_ack(packet)
            return

    def _handle_inbound_publish(self, packet):
        """Fire callbacks + (for QoS 1) send PUBACK."""
        # Pattern handlers fire FIRST so user code can branch on
        # specific topics; the global on_message fires after.
        for pattern, handler in self._pattern_handlers:
            if topic_matches(packet.topic, pattern):
                handler(packet.topic, packet.payload)
        self.on_message(packet.topic, packet.payload)
        if packet.qos == 1:
            self._tx_queue.insert(0, encode_puback(packet_id=packet.packet_id))

    def _handle_oversized(self, packet):
        """Apply the configured WhenOversized policy."""
        if self._when_oversized == WhenOversized.DROP_SILENT:
            pass  # Drop without notification.
        elif self._when_oversized == WhenOversized.DROP_WITH_EVENT:
            self.on_oversized(packet.topic, packet.reported_length)
        elif self._when_oversized == WhenOversized.DISCONNECT:
            raise MQTTProtocolError(
                f"oversized message on topic {packet.topic!r} "
                f"({packet.reported_length} bytes)",
            )
        # PUBACK QoS 1 oversized messages even when dropping payload —
        # broker would otherwise retransmit.
        if packet.qos == 1 and self._when_oversized != WhenOversized.DISCONNECT:
            self._tx_queue.insert(0, encode_puback(packet_id=packet.packet_id))

    def _handle_ack(self, packet):
        """Match an inbound CONNACK / SUBACK / PUBACK / etc. to its pending entry."""
        if packet.packet_type == PACKET_CONNACK:
            self._handle_connack(packet)
            return
        if packet.packet_type == PACKET_PINGRESP:
            self._discard_pending(Awaiting.PINGRESP, packet_id=None)
            return
        if packet.packet_type == PACKET_PUBACK:
            in_flight = self._in_flight.discard(packet.packet_id)
            if in_flight is None:
                raise MQTTProtocolError(
                    f"PUBACK for unknown packet_id {packet.packet_id}",
                )
            if in_flight.callback is not None:
                in_flight.callback()
            return
        if packet.packet_type == PACKET_SUBACK:
            self._discard_pending(
                Awaiting.SUBACK,
                packet_id=packet.packet_id,
                callback_arg=packet.granted_qos,
            )
            self._in_flight.discard(packet.packet_id)  # Free the id.
            return
        if packet.packet_type == PACKET_UNSUBACK:
            self._discard_pending(Awaiting.UNSUBACK, packet_id=packet.packet_id, callback_arg=None)
            self._in_flight.discard(packet.packet_id)
            return

    def _handle_connack(self, packet):
        """CONNACK return-code 0 = success, anything else = failure."""
        self._discard_pending(Awaiting.CONNACK, packet_id=None)
        if packet.return_code != 0:
            self._last_error = MQTTConnectError(
                f"broker rejected CONNECT (return code {packet.return_code})",
                return_code=packet.return_code,
            )
            self._state = ProtocolState.FAILED
            return
        self._state = ProtocolState.CONNECTED
        self._next_ping_due_ticks = self._deadline(self._ping_interval_ms)
        self.on_connect()

    def _discard_pending(self, awaiting, *, packet_id, callback_arg=None):
        """Find + remove the matching :class:`PendingResponse`; fire callback."""
        for index, pending in enumerate(self._pending_responses):
            if pending.awaiting != awaiting:
                continue
            if packet_id is not None and pending.packet_id != packet_id:
                continue
            self._pending_responses.pop(index)
            if pending.callback is not None:
                if callback_arg is not None:
                    pending.callback(callback_arg)
                else:
                    pending.callback()
            return

    # ------------------------------------------------------------------
    # Internal — deadlines + keepalive
    # ------------------------------------------------------------------

    def _check_deadlines(self, now_ms):
        """Retry / fault on expired in-flight + pending entries."""
        # In-flight (QoS 1 PUBLISH).
        for entry in list(self._in_flight):
            if self._ticks_diff(entry.deadline_ticks, now_ms) > 0:
                continue
            if entry.retry_count >= self._publish_retry_max:
                self._in_flight.discard(entry.packet_id)
                self._last_error = MQTTError(
                    f"PUBLISH packet_id {entry.packet_id} exceeded "
                    f"retry limit {self._publish_retry_max}",
                )
                self._state = ProtocolState.FAILED
                return
            entry.retry_count += 1
            entry.deadline_ticks = self._deadline(self._ack_timeout_ms)
            # Re-queue the original bytes — set the DUP flag (bit 3 of
            # byte 0) per MQTT 3.1.1 4.3.2.
            retry_packet = bytearray(entry.packet_bytes)
            retry_packet[0] |= 0x08
            self._tx_queue.append(bytes(retry_packet))

        # Pending (CONNACK / SUBACK / UNSUBACK / PINGRESP).
        for pending in list(self._pending_responses):
            if self._ticks_diff(pending.deadline_ticks, now_ms) > 0:
                continue
            self._pending_responses.remove(pending)
            self._last_error = MQTTError(
                f"timed out awaiting {pending.awaiting}",
            )
            self._state = ProtocolState.FAILED
            return

    def _check_keepalive(self, now_ms):
        """Send a PINGREQ when half the keepalive interval has elapsed."""
        if self._state != ProtocolState.CONNECTED:
            return
        if self._ticks_diff(self._next_ping_due_ticks, now_ms) > 0:
            return
        # Already awaiting a PINGRESP?  Don't double-send.
        for pending in self._pending_responses:
            if pending.awaiting == Awaiting.PINGRESP:
                return
        self._tx_queue.append(PACKET_PINGREQ)
        self._pending_responses.append(
            PendingResponse(
                awaiting=Awaiting.PINGRESP,
                deadline_ticks=self._deadline(self._ack_timeout_ms),
            ),
        )
        self._next_ping_due_ticks = self._deadline(self._ping_interval_ms)

    def _deadline(self, offset_ms):
        """Return a tick value that's *offset_ms* in the future."""
        return self._ticks_add(self._ticks_ms(), offset_ms)
