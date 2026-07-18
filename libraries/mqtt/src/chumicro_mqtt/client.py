"""MQTT 3.1.1 client built on chumicro-sockets + chumicro-timing.

:class:`MQTTClient` is the entry point: no threads, no async, just
cooperative dispatch in the caller's tick loop.
"""

import errno
from collections import deque

from chumicro_mqtt._wire import (
    PACKET_CONNACK,
    PACKET_DISCONNECT,
    PACKET_PINGREQ,
    PACKET_PINGRESP,
    PACKET_PUBACK,
    PACKET_SUBACK,
    PACKET_UNSUBACK,
    MQTTBackpressureError,
    MQTTConnectError,
    MQTTError,
    MQTTProtocolError,
    PacketDecoder,
    ParsedAck,
    ParsedPublish,
    UnsupportedQoSError,
    _OversizedMessage,
    encode_connect,
    encode_puback,
    encode_publish,
    encode_subscribe,
    encode_unsubscribe,
)

# Poll-interest bits for ``io_interest``, mirroring ``chumicro_runner.IO_READ``
# / ``IO_WRITE`` by value. Held as literals so the client takes no dependency
# edge on the runner (it can run under a bring-your-own scheduler).
_IO_READ = 1
_IO_WRITE = 2

# ---------------------------------------------------------------------------
# Connection state + pending-work tracking
# ---------------------------------------------------------------------------


class ProtocolState:
    """Connection lifecycle states.

    Transitions run forward except after a fault::

      DISCONNECTED -> AWAITING_TRANSPORT -> CONNECTING -> CONNECTED
                                                       \\-> FAILED -> AWAITING_TRANSPORT (self-heal)
                                                                   -> DISCONNECTED
                                          CONNECTED -> DISCONNECTED

    ``AWAITING_TRANSPORT`` brings the socket up across ticks via a
    :class:`SocketConnector` (DNS / TCP / TLS). ``CONNECTING`` is the MQTT
    phase: the socket is up and CONNECT is queued, waiting for CONNACK. A
    client built with a pre-connected socket starts at ``CONNECTING``.
    """

    DISCONNECTED = "disconnected"
    AWAITING_TRANSPORT = "awaiting_transport"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"


class InboundPublish:
    """One inbound PUBLISH returned by :meth:`MQTTClient.next_message`.

    ``topic`` is the full topic string; ``payload`` is the raw
    ``bytes`` exactly as received (decode at the consumer if the
    payload is text).
    """

    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload

    def __repr__(self):
        return f"InboundPublish(topic={self.topic!r}, {len(self.payload)} bytes)"


class _InboundWait:
    # A runner wait that carries only io_socket=None: the client owns the
    # socket poll itself, so this generator just re-checks the queue each tick.
    io_socket = None


_INBOUND_WAIT = _InboundWait()


# Tags identifying which broker response a pending work-item expects.
_AWAIT_CONNACK = "connack"
_AWAIT_PINGRESP = "pingresp"
_AWAIT_PUBACK = "puback"
_AWAIT_SUBACK = "suback"
_AWAIT_UNSUBACK = "unsuback"

# Self-heal reconnect backoff. Retrying every tick would storm the broker and
# drain the battery on a persistent failure, so the first retry is immediate
# and each later one doubles the wait from _SELF_HEAL_BACKOFF_BASE_MS up to
# _SELF_HEAL_BACKOFF_CAP_MS. A successful CONNACK resets the schedule.
_SELF_HEAL_BACKOFF_BASE_MS = 1000
_SELF_HEAL_BACKOFF_CAP_MS = 60000

# CONNACK codes retrying can't fix: bad protocol version (1), identifier
# rejected (2), bad credentials (4), not authorized (5). The client latches
# permanent-failure for these; code 3 (server unavailable) stays transient.
_PERMANENT_CONNACK_CODES = (1, 2, 4, 5)

# Bound on the next_message() inbound queue (drop-oldest when full), so a slow
# consumer loses the oldest messages rather than growing the heap.
_MAX_INBOUND_QUEUE_SIZE = 16


class InFlightPublish:
    """One outstanding QoS 1 PUBLISH awaiting a PUBACK.

    Carries the bytes ready to re-send, a retry counter, a deadline
    (ticks), and an optional callback that fires once on PUBACK.
    """

    def __init__(self, packet_id, packet_bytes, deadline_ticks, callback=None):
        self.packet_id = packet_id
        self.packet_bytes = packet_bytes
        self.retry_count = 0
        self.deadline_ticks = deadline_ticks
        self.callback = callback
        # DUP-flagged retransmit bytes, built once on first retry and reused
        # so a retry doesn't re-copy packet_bytes each time.
        self.dup_packet_bytes = None


class PendingResponse:
    """A non-publish response we're waiting for (CONNACK / SUBACK / UNSUBACK / PINGRESP).

    Each carries an ``_AWAIT_*`` tag, a deadline, an optional packet_id,
    and an optional callback that fires once on receipt. SUBACK entries
    also carry the ``topic`` so a rejected filter can be evicted before
    the client faults.
    """

    def __init__(self, awaiting, deadline_ticks, packet_id=None, callback=None, topic=None):
        self.awaiting = awaiting
        self.deadline_ticks = deadline_ticks
        self.packet_id = packet_id
        self.callback = callback
        self.topic = topic


# ---------------------------------------------------------------------------
# WhenOversized policy
# ---------------------------------------------------------------------------


class WhenOversized:
    """Policy for inbound PUBLISH whose total wire size exceeds ``rx_buffer_size``."""

    #: Drop the payload silently and PUBACK the broker.
    DROP_SILENT = "drop_silent"

    #: Default. Drop the payload, fire ``on_oversized(reported_length, topic)``,
    #: still PUBACK so the broker doesn't retransmit. ``topic`` is ``None``
    #: when the inbound topic itself overflowed (never decoded), so guard it
    #: before calling string methods.
    DROP_WITH_EVENT = "drop_with_event"

    #: Treat as a protocol error and disconnect. Use when payloads are
    #: expected to fit the configured cap.
    DISCONNECT = "disconnect"


def _no_callback(*_args, **_kwargs):
    return None


def _new_tx_queue(maxlen):
    # MicroPython / CircuitPython need flags=1 to enable appendleft; CPython
    # rejects the third arg, so try the embedded shape first and fall back.
    try:
        return deque((), maxlen, 1)
    except TypeError:  # CPython: 2-arg constructor, appendleft already supported.
        return deque((), maxlen)


def _force_non_blocking(socket):
    # The tick-based RX path needs non-blocking recv, but some MP TLS adapters
    # lack setblocking entirely, so probe for it and tolerate its absence.
    setblocking = getattr(socket, "setblocking", None)
    if setblocking is None:
        return
    try:
        setblocking(False)
    except (OSError, AttributeError):  # pragma: no cover - defensive
        pass


# ---------------------------------------------------------------------------
# MQTTClient
# ---------------------------------------------------------------------------


class MQTTClient:
    """Non-blocking MQTT 3.1.1 client (QoS 0 + 1).

    Construct with an already-connected TCP client socket (``send`` /
    ``recv_into`` / ``close`` / ``setblocking`` / ``settimeout``) and
    user knobs, then drive via :meth:`check` / :meth:`handle` from a
    runner tick or a hand-rolled loop.  All callbacks fire from
    :meth:`handle`, never from a thread or interrupt.

    For config-driven construction, see :meth:`from_config`, a
    one-line factory that reads broker host/port + identity + auth
    from ``runtime_config.msgpack``.
    """

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        radio: object | None = None,
        ssl_context: object | None = None,
        socket: object | None = None,
        transport_factory: object | None = None,
        ticks: object | None = None,
    ) -> "MQTTClient":
        """Build an :class:`MQTTClient` from runtime config.

        Reads ``mqtt.broker.host`` / ``mqtt.broker.port`` (required unless a
        *socket* or *transport_factory* override is passed), plus optional
        ``mqtt.client_id`` / ``mqtt.keep_alive_seconds`` / ``mqtt.username`` /
        ``mqtt.password`` / ``mqtt.when_disconnected`` (default ``"queue"``).
        A *socket* or *transport_factory* override bypasses the auto-built
        factory. *ticks* forwards to the constructor's clock seam so tests
        can inject a fake clock through this path too.

        Raises:
            ValueError: *config* is not a mapping-like object.
            MissingConfigKey: A required broker key is missing.
        """
        if not hasattr(config, "get"):
            raise ValueError(
                "from_config requires a mapping-like config "
                f"(RuntimeConfig or dict), got {type(config).__name__}",
            )
        if socket is None and transport_factory is None:
            # Lazy import so users who pass their own socket / transport_factory
            # never pull chumicro_sockets into the deploy graph.
            try:
                from chumicro_mqtt.sockets_factory import (  # noqa: PLC0415 - lazy
                    chumicro_sockets_connector_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_mqtt.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or "
                    "not on the board); pass transport_factory= or "
                    "socket= explicitly.",
                ) from exception

            transport_factory = chumicro_sockets_connector_factory(
                config, radio=radio, ssl_context=ssl_context,
            )
        return cls(
            socket=socket,
            transport_factory=transport_factory,
            client_id=config.get("mqtt.client_id", "chumicro-mqtt"),
            keep_alive_seconds=config.get("mqtt.keep_alive_seconds", 60),
            username=config.get("mqtt.username"),
            password=config.get("mqtt.password"),
            when_disconnected=config.get("mqtt.when_disconnected", "queue"),
            ticks=ticks,
        )

    def __init__(
        self,
        socket: object | None = None,
        *,
        transport_factory: object | None = None,
        client_id: str,
        keep_alive_seconds: int = 60,
        ack_timeout_seconds: float = 5.0,
        publish_retry_max: int = 3,
        username: str | None = None,
        password: str | None = None,
        clean_session: bool = True,
        will_topic: str | None = None,
        will_message: bytes | None = None,
        will_qos: int = 0,
        will_retain: bool = False,
        rx_buffer_size: int | None = None,
        when_oversized: WhenOversized = WhenOversized.DROP_WITH_EVENT,
        when_disconnected: str = "queue",
        pre_connect_queue_size: int = 8,
        recv_budget_per_tick: int = 1024,
        max_tx_queue_size: int = 20,
        send_timeout_seconds: float | None = None,
        ticks: object | None = None,
    ) -> None:
        """Wire up the client.

        Args:
            socket: An already-connected, non-blocking object exposing
                ``recv_into`` / ``send`` / ``close`` / ``setblocking``. The
                client takes ownership and :meth:`disconnect` closes it. May
                be ``None`` when *transport_factory* is provided.
            transport_factory: Optional zero-arg callable returning a
                :class:`~chumicro_sockets.SocketConnector`, the non-blocking
                connect state machine. Used when *socket* is ``None`` (initial
                connect) and on self-heal after a fault; :meth:`connect` and
                self-heal drive it across ticks so the runner never blocks.
                Without a factory, the caller supplies *socket* and manages
                reconnect. The factory only fires from ``connect()`` /
                self-heal, never from ``__init__``.
            client_id: MQTT client identifier. Must be unique per broker.
            keep_alive_seconds: Broker idle timeout. PINGREQ runs at half
                this interval client-side.
            ack_timeout_seconds: Per-ack deadline (PUBACK / SUBACK / etc.).
                Triggers a retry (PUBLISH) or fault (everything else), and
                bounds each connector-driven transport attempt.
            publish_retry_max: Max QoS 1 PUBLISH retries before giving up and
                transitioning to FAILED.
            username: Optional auth username (paired with *password*).
            password: Optional auth password.
            clean_session: ``False`` resumes persistent broker session state
                for QoS 1+ retransmit across reconnects.
            will_topic: Topic for the broker's last-will message, published on
                an uncleanly-dropped connection. ``None`` disables the will.
            will_message: Payload for the broker's last-will message.
            will_qos: QoS for the will message (0 or 1).
            will_retain: ``True`` retains the will on the broker.
            rx_buffer_size: Steady-state RX buffer size (default 256). A
                PUBLISH that fits parses inline with no allocation and delivers
                its full payload; a larger one routes through the oversized
                tier (see :class:`WhenOversized`) and its payload is discarded.
                Size this up to the largest PUBLISH a consumer must receive
                intact.
            when_oversized: Policy for inbound messages larger than
                ``rx_buffer_size``. See :class:`WhenOversized`.
            when_disconnected: Policy for :meth:`publish` called before
                ``CONNECTED`` (the async-connect and self-heal windows).
                ``"queue"`` (default) buffers into a bounded queue drained on
                CONNACK (a full queue raises :class:`MQTTBackpressureError`);
                ``"raise"`` raises :class:`MQTTError` immediately.
            pre_connect_queue_size: Bound on the pre-connect publish queue
                (default 8). A small bound absorbs a short burst during the
                connect window; raise it for a publisher that produces faster
                than it reconnects.
            recv_budget_per_tick: Cap on the bytes the single per-tick
                ``recv_into`` pulls off the socket (default 1024). Also bounds
                how many packets one tick dispatches and how large a PUBACK
                batch it owes. Raise for higher throughput at the cost of
                per-tick latency.
            max_tx_queue_size: Maximum pending outbound packets (default 20).
                Appending past the cap raises :class:`MQTTBackpressureError`.
            send_timeout_seconds: Maximum time the socket can stay non-writable
                with a packet queued before the client transitions to
                ``FAILED``. ``None`` (default) inherits ``ack_timeout_seconds``.
                Re-arms on every send that makes progress, so only a stalled
                socket trips it.
            ticks: Optional tick source exposing ``ticks_ms`` / ``ticks_diff``
                / ``ticks_add`` (the ``chumicro_timing.ticks`` shape). Defaults
                to the real clock; tests pass ``FakeTicks``.
        """
        if socket is None and transport_factory is None:
            raise ValueError(
                "MQTTClient requires either a connected socket or a "
                "transport_factory (or both; factory is used for self-heal "
                "after wifi-drop)."
            )
        self._socket = socket
        self._transport_factory = transport_factory
        self._connector = None
        # Overall deadline for the in-flight transport attempt: connectors
        # never time out on their own, so a black-holed connect would park in
        # AWAITING_TRANSPORT forever without this. Armed when a connector is
        # built, cleared when it terminates.
        self._transport_deadline_ticks = None
        if self._socket is not None:
            _force_non_blocking(self._socket)
        self._user_wants_connected = False
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
        if when_disconnected not in ("queue", "raise"):
            raise ValueError(
                "when_disconnected must be 'queue' or 'raise', "
                f"got {when_disconnected!r}",
            )
        self._when_disconnected = when_disconnected
        self._pre_connect_queue_size = pre_connect_queue_size
        # Publishes issued before CONNECTED buffer here under the "queue"
        # policy, then drain on CONNACK in receipt order. Bounds are enforced
        # in _publish_disconnected, not left to the deque's own overflow.
        self._pre_connect_queue = _new_tx_queue(pre_connect_queue_size)
        self._recv_budget_per_tick = recv_budget_per_tick
        self._max_tx_queue_size = max_tx_queue_size
        if send_timeout_seconds is None:
            self._send_timeout_ms = self._ack_timeout_ms
        else:
            self._send_timeout_ms = int(send_timeout_seconds * 1000)

        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        self._ticks = ticks

        decoder_kwargs = {}
        if rx_buffer_size is not None:
            decoder_kwargs["rx_buffer_size"] = rx_buffer_size
        self._decoder_kwargs = decoder_kwargs
        self._decoder = PacketDecoder(**decoder_kwargs)

        self.state = ProtocolState.DISCONNECTED
        # In-flight QoS-1 PUBLISHes keyed by packet-id; ids come from
        # _allocate_packet_id (wraparound + collision-avoidance).
        self._in_flight = {}
        self._next_packet_id = 1
        self._pending_responses = []
        # Desired subscription set: topic -> [requested_qos, one-shot
        # on_subscribe]. The second slot fires on the first SUBACK granting the
        # topic, then clears. Maintained by subscribe()/unsubscribe() and
        # replayed on each CONNACK (see _replay_subscriptions).
        self._subscriptions = {}
        # 64-slot headroom above the user cap so the QoS-1 retry path and
        # PINGREQ can't lose protocol packets when the queue is at the user
        # cap. _enqueue_user_tx enforces the user cap; _enqueue_internal_tx
        # checks this hard cap.
        self._tx_queue_hard_cap = max_tx_queue_size + 64
        self._tx_queue = _new_tx_queue(self._tx_queue_hard_cap)
        self._partial_send = None  # (memoryview, offset) when last send was short.
        # Reused across recv ticks so a QoS-0 subscriber doesn't allocate a
        # fresh list every _read_inbound; emptied at the start of each tick.
        self._pending_pubacks = []
        # True while a coalesced PUBACK batch is still queued unsent. Gates the
        # next recv (see _recv_suppressed) so the ack backlog stays bounded.
        self._puback_batch_queued = False
        # Deadline while a packet is queued without send progress. None when
        # the queue is empty or the last drain made progress. Surfaced via
        # next_deadline so the runner wakes by it.
        self._send_deadline_ticks = None

        self._next_ping_due_ticks = 0
        # keep_alive_seconds == 0 means "keepalive disabled" (MQTT
        # 3.1.1 §3.1.2.10): no PINGREQ traffic at all.  A non-zero value
        # pings at half the interval, floored at 1 s.
        self._keepalive_enabled = keep_alive_seconds > 0
        self._ping_interval_ms = max(1000, keep_alive_seconds * 1000 // 2)

        # Callbacks default to no-ops so handlers can call without branching.
        self.on_message = _no_callback
        self.on_connect = _no_callback
        self.on_disconnect = _no_callback
        self.on_subscribe = _no_callback
        self.on_unsubscribe = _no_callback
        self.on_publish = _no_callback
        self.on_oversized = _no_callback
        # next_message() lazily builds the inbound queue and flips data
        # delivery from the callbacks to it (the receive-stream surface).
        self._inbound_queue = None
        self.last_error = None
        # Self-heal reconnect pacing. _self_heal_attempts counts consecutive
        # failed reconnects (reset on CONNACK); _self_heal_retry_at_ticks gates
        # the next attempt; _permanent_failure latches on a CONNACK rejection
        # retrying can't fix, stopping self-heal until the next connect().
        self._self_heal_attempts = 0
        self._self_heal_retry_at_ticks = None
        self._permanent_failure = False
        # hold() latches this to suspend timer-driven reconnection; connect()
        # releases it.
        self._reconnect_held = False

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def connect(self):
        """Express the intent "be connected", acting on it now.

        An intent, not a state guard: DISCONNECTED begins the connect
        sequence; FAILED means "self-heal now" (reset backoff and dial via
        the same path a timer uses); CONNECTED / CONNECTING /
        AWAITING_TRANSPORT are an idempotent no-op. Every state clears any
        :meth:`hold` and latches the intent.
        """
        # Clear any caller hold (connect() is the sole release) and latch
        # "be connected" in every state.
        self._reconnect_held = False
        self._user_wants_connected = True
        if self.state == ProtocolState.DISCONNECTED:
            # Fresh connect: clear the permanent-failure latch and reset
            # the self-heal backoff from a prior FAILED session.
            self._permanent_failure = False
            self._self_heal_attempts = 0
            self._self_heal_retry_at_ticks = None
            if self._socket is None:
                try:
                    self._connector = self._transport_factory()
                except Exception as factory_error:  # noqa: BLE001 - documented: all factory errors -> FAILED
                    self.last_error = MQTTError(
                        f"connector factory failed: {factory_error}",
                    )
                    self.state = ProtocolState.FAILED
                    return
                self._transport_deadline_ticks = self._deadline(self._ack_timeout_ms)
                self.state = ProtocolState.AWAITING_TRANSPORT
                return
            self._enqueue_connect_packet()
            self.state = ProtocolState.CONNECTING
            return
        if self.state == ProtocolState.FAILED:
            # "Self-heal now": clear the permanent latch (one fresh
            # attempt, as DISCONNECTED grants) and reset the backoff so the
            # next handle() tick dials via the shared self-heal path.
            self._permanent_failure = False
            self._self_heal_attempts = 0
            self._self_heal_retry_at_ticks = None
            return
        # AWAITING_TRANSPORT / CONNECTING / CONNECTED: intent already
        # satisfied, so this is an idempotent no-op beyond the hold clear.

    def hold(self):
        """Suspend timer-driven reconnection until the next :meth:`connect`.

        Use it when the app knows the link is down (a self-heal timer dialing
        a dead radio wastes cycles). A pure intent latch: no state change and
        no cancel of an in-flight dial. While FAILED it suppresses self-heal
        (no dial, state stays FAILED, ``next_deadline`` parks) while publishes
        still buffer per ``when_disconnected``. ``connect()`` is the release.
        """
        self._reconnect_held = True

    def _enqueue_connect_packet(self):
        # Encode CONNECT, queue it, and arm the CONNACK pending-response slot.
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
        self._enqueue_user_tx(packet)
        self._pending_responses.append(
            PendingResponse(
                awaiting=_AWAIT_CONNACK,
                deadline_ticks=self._deadline(self._ack_timeout_ms),
            ),
        )

    def disconnect(self):
        """Queue a DISCONNECT packet, close the socket, mark DISCONNECTED.

        Idempotent: a second call from DISCONNECTED is a no-op. From
        CONNECTED / CONNECTING it sends a best-effort DISCONNECT then closes;
        from AWAITING_TRANSPORT it cancels the in-flight connector; from
        FAILED it just closes. ``on_disconnect`` fires exactly once on the
        transition to DISCONNECTED, and any send/close error is swallowed so
        the client always lands in a known state.
        """
        if self.state == ProtocolState.DISCONNECTED:
            return
        if self.state == ProtocolState.AWAITING_TRANSPORT:
            if self._connector is not None:
                self._connector.cancel()
                self._connector = None
        elif self.state != ProtocolState.FAILED:
            try:
                self._send_raw(PACKET_DISCONNECT)
            except Exception:  # noqa: BLE001 - disconnect is best-effort  # pragma: no cover - defensive
                pass
        try:
            if self._socket is not None:
                self._socket.close()
        except Exception:  # noqa: BLE001 - disconnect is best-effort  # pragma: no cover - defensive
            pass
        # Null the socket and drop socket-bound state so a later connect()
        # routes through the connector factory instead of re-arming CONNECT
        # against the closed fd, and no stale queued/inbound packet survives.
        self._socket = None
        self._reset_transient_state()
        # Drop publishes queued for a connect that will never come. Self-heal
        # keeps the queue (_reset_transient_state leaves it alone), so only a
        # deliberate disconnect discards buffered publishes.
        self._pre_connect_queue = _new_tx_queue(self._pre_connect_queue_size)
        self.state = ProtocolState.DISCONNECTED
        self._user_wants_connected = False
        # A deliberate teardown drops every reconnect intent, including a
        # caller hold; a later connect() starts from a clean slate.
        self._reconnect_held = False
        self.on_disconnect()

    def _reset_transient_state(self):
        # A fresh deque, not clear(): MicroPython/CircuitPython deque lacks it.
        self._tx_queue = _new_tx_queue(self._tx_queue_hard_cap)
        self._partial_send = None
        self._puback_batch_queued = False
        self._send_deadline_ticks = None
        self._transport_deadline_ticks = None
        self._pending_responses.clear()
        # Fresh decoder drops any half-read inbound packet from the old socket.
        self._decoder = PacketDecoder(**self._decoder_kwargs)

    def set_will(
        self,
        topic: str | None,
        message: bytes | None = None,
        *,
        qos: int = 0,
        retain: bool = False,
    ):
        """Update the Last Will + Testament, taking effect on the next CONNECT.

        The current connection already registered its will at CONNECT time
        and cannot change it in flight; the update lands on the next
        :meth:`connect` or self-heal reconnect.

        Args:
            topic: Will topic. ``None`` disables the will entirely.
            message: Will payload (bytes). ``None`` becomes empty bytes.
            qos: Will QoS (0 or 1).
            retain: ``True`` retains the will on the broker.

        Raises:
            UnsupportedQoSError: ``qos > 1``.
        """
        if qos > 1:
            raise UnsupportedQoSError(
                "will_qos must be 0 or 1; QoS 2 is reserved-not-implemented",
            )
        self._will_topic = topic
        self._will_message = message
        self._will_qos = qos
        self._will_retain = retain

    # ------------------------------------------------------------------
    # Public publish / subscribe / unsubscribe
    # ------------------------------------------------------------------

    def publish(
        self,
        topic: str,
        payload: bytes | str,
        *,
        qos: int = 0,
        retain: bool = False,
        on_publish: object | None = None,
    ) -> None:
        """Queue a PUBLISH packet for *topic*.

        QoS 0: queued and considered delivered once it reaches the wire
        (the optional *on_publish* fires from the next :meth:`handle`).

        QoS 1: in-flight entry is opened with the packet bytes + the
        callback.  PUBACK matches on packet_id and fires the callback
        exactly once.  Retries up to *publish_retry_max* on ack timeout.

        Args:
            topic: Publish topic, sent on the wire as written.
            payload: ``bytes`` / ``str``.  ``str`` is auto-encoded as UTF-8.
            qos: 0 or 1.  QoS 2 raises :class:`UnsupportedQoSError`.
            retain: True for retained messages.
            on_publish: Callback ``(topic, payload_bytes)`` fired on
                successful delivery.

        Before ``CONNECTED`` (the async-connect and self-heal windows)
        the ``when_disconnected`` policy applies: ``"queue"`` (default)
        buffers into a bounded pre-connect queue drained on CONNACK,
        and ``"raise"`` raises :class:`MQTTError`.

        Raises:
            MQTTError: ``when_disconnected="raise"`` and the client is
                not yet CONNECTED.
            MQTTBackpressureError: the tx queue is full, or the
                pre-connect queue is full under the ``"queue"`` policy.
        """
        if qos > 1:
            raise UnsupportedQoSError(
                "qos must be 0 or 1; QoS 2 is reserved-not-implemented",
            )
        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = bytes(payload)  # pragma: no cover - bytes-passthrough trivial path

        if self.state != ProtocolState.CONNECTED:
            self._publish_disconnected(topic, payload_bytes, qos, retain, on_publish)
            return
        self._do_publish(topic, payload_bytes, qos, retain, on_publish)

    def _publish_disconnected(self, topic, payload_bytes, qos, retain, on_publish):
        if self._when_disconnected == "raise":
            raise MQTTError(
                f"publish() requires CONNECTED state, was {self.state}",
            )
        queue = self._pre_connect_queue
        if len(queue) >= self._pre_connect_queue_size:
            # "queue": bounded means bounded.
            raise MQTTBackpressureError(
                f"pre-connect publish queue full "
                f"({self._pre_connect_queue_size}); call handle() to "
                "connect and drain, then retry",
            )
        queue.append((topic, payload_bytes, qos, retain, on_publish))

    def _drain_pre_connect_queue(self):
        # Flush queued pre-connect publishes onto the wire, oldest first.
        queue = self._pre_connect_queue
        while queue:
            topic, payload_bytes, qos, retain, on_publish = queue.popleft()
            self._do_publish(topic, payload_bytes, qos, retain, on_publish)

    def _do_publish(self, topic, payload_bytes, qos, retain, on_publish):
        # Encode and enqueue a resolved PUBLISH; the caller is CONNECTED.
        if qos == 0:
            packet = encode_publish(
                topic=topic, payload=payload_bytes, qos=0, retain=retain,
            )
            # QoS 0 has no ack: the on_publish callback fires via a marker
            # entry once the bytes hit the wire. Packet + marker enqueue as one
            # capacity-checked unit so the pair can't half-land.
            if on_publish is not None or self.on_publish is not _no_callback:
                self._enqueue_user_tx(
                    packet,
                    ("__qos0_callback__", on_publish, topic, payload_bytes),
                )
            else:
                self._enqueue_user_tx(packet)
            return

        packet_id = self._allocate_packet_id()
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

        # _allocate_packet_id already refuses live ids, so this never
        # overwrites an entry; check defensively against a future refactor.
        if packet_id in self._in_flight:
            raise KeyError(f"packet_id {packet_id} already in flight")
        self._in_flight[packet_id] = InFlightPublish(
            packet_id=packet_id,
            packet_bytes=packet,
            deadline_ticks=self._deadline(self._ack_timeout_ms),
            callback=_wrapped_callback,
        )
        try:
            self._enqueue_user_tx(packet)
        except MQTTBackpressureError:
            # Roll back the in-flight allocation so the caller can retry
            # cleanly without leaking a packet_id.
            self._in_flight.pop(packet_id, None)
            raise

    def subscribe(
        self,
        topic: str,
        qos: int = 0,
        *,
        on_subscribe: object | None = None,
    ) -> None:
        """Declare a subscription for *topic*, valid in any state.

        A declaration, not a wire command: it records *topic* in the desired
        subscription set. When already ``CONNECTED`` the SUBSCRIBE also goes on
        the wire now; in any other state the first CONNACK's replay path
        (:meth:`_replay_subscriptions`) sends it. So a device can declare its
        subscriptions once at startup instead of threading them through
        ``on_connect``.

        Args:
            topic: Topic filter (``+`` / ``#`` wildcards ok), on the wire as
                written.
            qos: 0 or 1.
            on_subscribe: One-shot ``(topic, granted_qos)`` fired on the first
                SUBACK granting *topic* (direct send or replay), then cleared
                so self-heal replays stay silent.

        Raises:
            MQTTBackpressureError: already CONNECTED and the tx queue is full.
        """
        def _wrapped(granted_qos):
            if on_subscribe is not None:
                on_subscribe(topic, granted_qos)
            self.on_subscribe(topic, granted_qos)

        # CONNECTED: send now, before recording the entry, so a full-queue
        # backpressure error leaves the desired-set untouched. The SUBACK
        # callback lives with the entry (its second slot), so the direct send
        # and a replay share one firing path in _handle_ack.
        if self.state == ProtocolState.CONNECTED:
            packet_id = self._allocate_packet_id()  # Reuse the id pool.
            packet = encode_subscribe(
                packet_id=packet_id, subscriptions=[(topic, qos)],
            )
            self._enqueue_user_tx(packet)
            self._pending_responses.append(
                PendingResponse(
                    awaiting=_AWAIT_SUBACK,
                    deadline_ticks=self._deadline(self._ack_timeout_ms),
                    packet_id=packet_id,
                    callback=None,
                    topic=topic,
                ),
            )
        self._subscriptions[topic] = [qos, _wrapped]

    def unsubscribe(self, topic, *, on_unsubscribe=None):
        """Retract a subscription for *topic*, valid in any state.

        Mirror of :meth:`subscribe`. Always drops *topic* from the desired set
        so a replay never re-issues it. When ``CONNECTED`` it also sends the
        UNSUBSCRIBE and fires *on_unsubscribe* on the UNSUBACK; otherwise it
        just retracts the declaration.
        """
        if self.state != ProtocolState.CONNECTED:
            # Not on the wire: retract the declaration, no traffic.
            self._subscriptions.pop(topic, None)
            return
        packet_id = self._allocate_packet_id()
        packet = encode_unsubscribe(packet_id=packet_id, topics=[topic])
        self._enqueue_user_tx(packet)
        self._subscriptions.pop(topic, None)

        def _wrapped():
            if on_unsubscribe is not None:
                on_unsubscribe(topic)
            self.on_unsubscribe(topic)

        self._pending_responses.append(
            PendingResponse(
                awaiting=_AWAIT_UNSUBACK,
                deadline_ticks=self._deadline(self._ack_timeout_ms),
                packet_id=packet_id,
                callback=_wrapped,
            ),
        )

    def next_message(self):
        """Suspend until the next inbound PUBLISH; return it, or ``None`` when parked.

        Generator for runner-driven receive loops registered via
        ``Runner.add_generator`` alongside the client itself::

            runner.add(client)                     # drives I/O each tick
            runner.add_generator(consume(client))

            def consume(client):
                while True:
                    message = yield from client.next_message()
                    if message is None:
                        break
                    handle(message.topic, message.payload)

        The first call switches inbound delivery from the ``on_message``
        callback to a bounded queue this drains; lifecycle callbacks keep
        firing either way. Returns an :class:`InboundPublish` while the queue
        holds one (draining even after a disconnect), then ``None`` once the
        client is parked for good and the queue is empty. A transient FAILED
        keeps the generator suspended, since self-heal may resume the stream.

        The queue is bounded at 16 messages (drop-oldest when full). This is
        the receive-stream surface for single-subscription consumers;
        multi-topic fan-out stays on the callbacks (pick one per client).
        """
        if self._inbound_queue is None:
            # 2-arg deque drops the oldest item when full on every runtime
            # (the TX queue raises instead, for backpressure).
            self._inbound_queue = deque((), _MAX_INBOUND_QUEUE_SIZE)
        while True:
            if self._inbound_queue:
                return self._inbound_queue.popleft()
            if self._inbound_stream_ended():
                return None
            yield _INBOUND_WAIT

    def _inbound_stream_ended(self):
        # True when the client can never deliver another PUBLISH: mirrors
        # next_deadline's parked-forever condition (a hold is only a suspend).
        if self.state == ProtocolState.DISCONNECTED:
            return True
        if self.state != ProtocolState.FAILED:
            return False
        return (
            self._transport_factory is None
            or not self._user_wants_connected
            or self._permanent_failure
        )

    # ------------------------------------------------------------------
    # Runner contract
    # ------------------------------------------------------------------

    def check(self, now_ms):  # noqa: ARG002 (runner contract uses now_ms)
        """Return ``True`` when the client wants a ``handle()`` this tick.

        Any non-terminal state is worth a tick, and ``FAILED`` qualifies so
        its self-heal branch keeps firing. ``DISCONNECTED``, a permanently
        failed client, and one held by :meth:`hold` are gated out.
        """
        if self.state == ProtocolState.FAILED and (
            self._permanent_failure or self._reconnect_held
        ):
            return False
        return self.state is not ProtocolState.DISCONNECTED

    # ------------------------------------------------------------------
    # Runner I/O interest (read by ``Runner.wait``)
    # ------------------------------------------------------------------

    @property
    def io_socket(self):
        """The MQTT socket-ish object while connected, connecting, or bringing
        up transport, else ``None``.

        In ``AWAITING_TRANSPORT`` it forwards to the connector's pollable so
        ``Runner.wait`` parks correctly between connect phases; in
        ``CONNECTING`` / ``CONNECTED`` it returns the socket as-is.
        ``DISCONNECTED`` and ``FAILED`` return ``None`` so the runner does not
        wake on a dead handle.
        """
        if self.state == ProtocolState.AWAITING_TRANSPORT:
            return self._connector.io_socket if self._connector is not None else None
        if self._socket is None:
            return None
        if self.state in (ProtocolState.DISCONNECTED, ProtocolState.FAILED):
            return None
        return self._socket

    def io_interest(self, now_ms):
        """Poll-interest bitmask (``_IO_READ`` / ``_IO_WRITE``) for ``Runner.wait``.

        The read bit is set while ``handle()`` would consume inbound bytes;
        the write bit while outbound bytes are queued or a connect phase needs
        writability. Live connections want read except while recv is
        suppressed for backpressure (see :meth:`_recv_suppressed`);
        ``AWAITING_TRANSPORT`` forwards to the connector. A partial send has no
        queue entry but still needs writability so the send can resume.
        """
        if self.state == ProtocolState.AWAITING_TRANSPORT:
            if self._connector is None:
                return 0
            connector_interest = self._connector.io_interest(now_ms)
            return (connector_interest & _IO_READ) | (connector_interest & _IO_WRITE)
        interest = 0
        if (
            self.state in (ProtocolState.CONNECTING, ProtocolState.CONNECTED)
            and not self._recv_suppressed()
        ):
            interest |= _IO_READ
        if self.state not in (ProtocolState.DISCONNECTED, ProtocolState.FAILED) and (
            len(self._tx_queue) > 0 or self._partial_send is not None
        ):
            interest |= _IO_WRITE
        return interest

    def io_error(self, now_ms, eventmask):  # noqa: ARG002 - runner contract uses now_ms
        """Runner hook: POLLERR / POLLHUP surfaced on the registered socket.

        Transitions to ``FAILED`` with ``last_error`` describing the event, so
        the next ``handle()`` tick fires self-heal. When the error fires during
        ``AWAITING_TRANSPORT``, the in-flight connector is cancelled first.
        """
        if self.state in (ProtocolState.DISCONNECTED, ProtocolState.FAILED):
            return
        if self.state == ProtocolState.AWAITING_TRANSPORT and self._connector is not None:
            self._connector.cancel()
            self._connector = None
            self._transport_deadline_ticks = None
        self.last_error = MQTTError(
            f"socket error from runner.wait (poll eventmask 0x{eventmask:x})",
        )
        self.state = ProtocolState.FAILED

    def next_deadline(self, now_ms):
        """Earliest tick at which ``handle()`` must run even on a quiet socket.

        Returns the minimum across the keepalive timer, each pending
        response's ack deadline, each in-flight QoS 1 retry deadline, and the
        send timeout when armed. ``None`` when no deadline applies.

        While ``AWAITING_TRANSPORT`` with no pollable yet (still resolving DNS)
        it returns *now_ms* to keep ticking the connector forward; once a
        pollable exists the runner parks on handshake progress, bounded by the
        transport-attempt deadline the client owns.
        """
        if self.state == ProtocolState.AWAITING_TRANSPORT:
            if self._connector is None:
                return None
            if self.io_socket is None:
                return now_ms
            nearest = self._connector.next_deadline(now_ms)
            attempt_deadline = self._transport_deadline_ticks
            if attempt_deadline is not None and (
                nearest is None
                or self._ticks.ticks_diff(attempt_deadline, nearest) < 0
            ):
                nearest = attempt_deadline
            return nearest
        if self.state == ProtocolState.FAILED:
            # A self-heal-active FAILED client wakes at its next backoff retry,
            # or immediately when none is armed yet, so the runner ticks
            # self-heal. A permanent failure, no factory, or a hold parks
            # forever (until connect()).
            if self._self_heal_active():
                if self._self_heal_retry_at_ticks is None:
                    return now_ms
                return self._self_heal_retry_at_ticks
            return None
        if self.state == ProtocolState.DISCONNECTED:
            return None
        ticks_diff = self._ticks.ticks_diff
        nearest = None
        if self.state == ProtocolState.CONNECTED:
            nearest = self._next_ping_due_ticks
        for pending in self._pending_responses:
            candidate = pending.deadline_ticks
            if nearest is None or ticks_diff(candidate, nearest) < 0:
                nearest = candidate
        for entry in self._in_flight.values():
            candidate = entry.deadline_ticks
            if nearest is None or ticks_diff(candidate, nearest) < 0:
                nearest = candidate
        if self._send_deadline_ticks is not None:
            candidate = self._send_deadline_ticks
            if nearest is None or ticks_diff(candidate, nearest) < 0:
                nearest = candidate
        return nearest

    def handle(self, now_ms):
        """One tick of progress.

        Checks ack deadlines and the keepalive timer first (so a wedged recv
        can't block timeout detection), then reads inbound bytes and
        dispatches complete packets (PUBACKs free in-flight slots; inbound
        QoS-1 publishes coalesce their PUBACKs into one front-of-queue batch),
        then drains the TX queue.

        In ``FAILED`` with self-heal active this tick builds a fresh connector
        and enters ``AWAITING_TRANSPORT``; without a factory, or while held, it
        stays ``FAILED``. ``AWAITING_TRANSPORT`` ticks check the transport
        deadline, then advance the connector: ``ready`` promotes the socket and
        moves to ``CONNECTING``, while a failure or a timed-out attempt moves
        to ``FAILED`` and schedules the next self-heal.

        *now_ms* is the per-tick timestamp the runner captures once and passes
        to every service. Source it from ``chumicro_timing.ticks_ms()`` (or the
        injected ``ticks`` object) so it shares the domain of the deadlines the
        client armed at ``connect()`` / ``publish()`` time.
        """
        if self.state == ProtocolState.FAILED:
            if not self._self_heal_active():
                return
            if (
                self._self_heal_retry_at_ticks is not None
                and self._ticks.ticks_diff(self._self_heal_retry_at_ticks, now_ms) > 0
            ):
                return  # Backoff interval not elapsed yet; wait for a later tick.
            self._arm_self_heal_backoff(now_ms)
            if not self._attempt_self_heal(now_ms):
                return
            # Self-heal succeeded (state is AWAITING_TRANSPORT). Fall through so
            # the connector gets one tick of progress immediately.
        if self.state == ProtocolState.AWAITING_TRANSPORT:
            # Deadline before I/O: a stalled attempt faults here without
            # giving the connector another tick.
            if self._check_transport_deadline(now_ms):
                return
            if not self._advance_connector(now_ms):
                return
            # Connector reached ready (CONNECTING, CONNECT queued): drain it.
        if self.state == ProtocolState.DISCONNECTED:
            return
        try:
            # Order: timeouts first so a wedged recv can't block deadline
            # detection, then read, then drain the tx queue.
            self._check_deadlines(now_ms)
            self._check_keepalive(now_ms)
            self._read_inbound(now_ms)
            self._drain_tx_queue()
        except MQTTError as error:
            self.last_error = error
            self.state = ProtocolState.FAILED
        except OSError as error:
            self.last_error = MQTTError(f"socket error: {error}")
            self.state = ProtocolState.FAILED

    def _self_heal_active(self):
        # True when a FAILED client will re-dial on its own: a factory, the
        # caller wanting to connect, no permanent rejection, and no hold.
        return (
            self._transport_factory is not None
            and self._user_wants_connected
            and not self._permanent_failure
            and not self._reconnect_held
        )

    def _arm_self_heal_backoff(self, now_ms):
        # Schedule the earliest tick the next self-heal attempt may run,
        # doubling the wait per attempt. Clamp the shift so a long outage
        # doesn't grow an ever-larger big-int before the cap clips it
        # (6 doublings of 1 s already exceeds the 60 s cap).
        if self._self_heal_attempts >= 6:
            delay_ms = _SELF_HEAL_BACKOFF_CAP_MS
        else:
            delay_ms = _SELF_HEAL_BACKOFF_BASE_MS << self._self_heal_attempts
            if delay_ms > _SELF_HEAL_BACKOFF_CAP_MS:
                delay_ms = _SELF_HEAL_BACKOFF_CAP_MS
            self._self_heal_attempts += 1
        self._self_heal_retry_at_ticks = self._deadline(delay_ms, now_ms=now_ms)

    def _attempt_self_heal(self, now_ms):
        # Build a fresh connector and enter AWAITING_TRANSPORT, returning True
        # on success. Best-effort: if transport_factory() raises (wifi still
        # down) the client stays FAILED and the next tick retries. The DNS /
        # TCP / TLS work happens across later ticks, so this does not block.
        # Close the dead socket best-effort so we don't leak file descriptors.
        try:
            if self._socket is not None:
                self._socket.close()
        except OSError:  # pragma: no cover - defensive
            pass
        self._socket = None
        # Keep the in-flight QoS 1 table on clean_session=False (the broker may
        # resume the session); clear it on clean_session=True below.
        self._reset_transient_state()
        if self._clean_session:
            self._in_flight = {}
            self._next_packet_id = 1
        try:
            self._connector = self._transport_factory()
        except Exception as factory_error:  # noqa: BLE001 - documented: all factory errors -> FAILED
            self.last_error = MQTTError(
                f"connector factory failed: {factory_error}",
            )
            return False
        self._transport_deadline_ticks = self._deadline(
            self._ack_timeout_ms, now_ms=now_ms,
        )
        self.state = ProtocolState.AWAITING_TRANSPORT
        self.last_error = None
        return True

    def _check_transport_deadline(self, now_ms):
        # Connectors never time out on their own, so a black-holed connect
        # would park forever without this. Returns True when it fired: the
        # connector is cancelled and the client is FAILED for the next tick.
        if self._transport_deadline_ticks is None:
            return False
        if self._ticks.ticks_diff(self._transport_deadline_ticks, now_ms) > 0:
            return False
        connector = self._connector
        phase = connector.state if connector is not None else "unknown"
        if connector is not None:
            connector.cancel()
            self._connector = None
        self._transport_deadline_ticks = None
        self.last_error = MQTTError(
            f"transport connect attempt timed out after "
            f"{self._ack_timeout_ms} ms (connector phase: {phase})",
        )
        self.state = ProtocolState.FAILED
        return True

    def _advance_connector(self, now_ms):
        # Tick the connector one phase; returns True once it reaches ready
        # (socket promoted, CONNECT queued, state CONNECTING). False while it
        # is still in flight or has failed (state then FAILED).
        connector = self._connector
        connector.tick(now_ms)
        if connector.state == "ready":
            self._socket = connector.socket
            self._connector = None
            self._transport_deadline_ticks = None
            _force_non_blocking(self._socket)
            self._enqueue_connect_packet()
            self.state = ProtocolState.CONNECTING
            return True
        if connector.state == "failed":
            self.last_error = MQTTError(
                f"connector failed: {connector.last_error}",
            )
            self._connector = None
            self._transport_deadline_ticks = None
            self.state = ProtocolState.FAILED
            return False
        return False

    # ------------------------------------------------------------------
    # Internal: in-flight packet-id allocation
    # ------------------------------------------------------------------

    def _allocate_packet_id(self):
        # Next free packet-id in the 1-65535 cycle (id 0 is spec-reserved);
        # raises OverflowError when every id is in flight, not reusing one.
        for _attempt in range(65535):
            candidate = self._next_packet_id
            self._next_packet_id += 1
            if self._next_packet_id > 65535:
                self._next_packet_id = 1
            if candidate not in self._in_flight:
                return candidate
        raise OverflowError(
            "MQTT in-flight table is full (65535 packet-ids in use)",
        )

    # ------------------------------------------------------------------
    # Internal: TX path
    # ------------------------------------------------------------------

    def _drain_tx_queue(self):
        # Send one user/protocol packet per tick so other runner services get
        # CPU time between sends. A coalesced PUBACK batch at the head (queued
        # by _read_inbound) flushes WITHOUT that budget, so the ack rate tracks
        # inbound dispatch. Items are bytes (a packet) or a
        # ("__qos0_callback__", callback, topic, payload) marker (no I/O).
        #
        # Resume a partial send first: its remainder must land before any new
        # packet, so this branch returns after one send attempt.
        if self._partial_send is not None:  # pragma: no cover - rare partial-send recovery path
            packet, offset = self._partial_send
            sent = self._send_raw(packet[offset:])
            new_offset = offset + sent
            if new_offset >= len(packet):
                self._partial_send = None
            else:
                self._partial_send = (packet, new_offset)
            self._update_send_deadline(sent)
            return  # One I/O attempt per tick.

        while True:
            # Drain leading QoS 0 callback markers (no I/O) before the next packet.
            self._drain_callback_markers()
            if not self._tx_queue:
                self._update_send_deadline(0)
                return
            packet = self._tx_queue[0]
            is_puback_batch = packet[0] == PACKET_PUBACK
            sent = self._send_raw(packet)
            if sent <= 0:  # pragma: no cover - non-blocking-EAGAIN backpressure path
                self._update_send_deadline(0)
                return  # Socket would block, wait for next tick.
            if sent < len(packet):  # pragma: no cover - rare partial-send path
                # Cache a memoryview so the resume path slices view[offset:]
                # zero-copy; packet is immutable bytes, safe to hold across ticks.
                self._partial_send = (memoryview(packet), sent)
                self._tx_queue.popleft()
                if is_puback_batch:
                    # Unsent tail still owes acks; _partial_send keeps recv suppressed.
                    self._puback_batch_queued = False
                self._update_send_deadline(sent)
                return
            self._tx_queue.popleft()
            self._update_send_deadline(sent)
            if is_puback_batch:
                self._puback_batch_queued = False
                continue  # Ack flush done; the packet budget is unspent.
            # Drain trailing QoS 0 markers so the just-sent PUBLISH's on_publish
            # fires this tick instead of next. Markers carry no I/O.
            self._drain_callback_markers()
            return

    def _update_send_deadline(self, bytes_sent):
        # Clear the deadline when nothing is queued. Otherwise arm it: re-arm on
        # progress so a steady drip doesn't false-fail; on no progress arm only
        # if none is set yet, else leave the running timer for _check_deadlines.
        if not self._tx_queue and self._partial_send is None:
            self._send_deadline_ticks = None
            return
        if bytes_sent > 0 or self._send_deadline_ticks is None:
            self._send_deadline_ticks = self._deadline(self._send_timeout_ms)

    def _drain_callback_markers(self):
        while self._tx_queue:
            head = self._tx_queue[0]
            if not (isinstance(head, tuple) and head[0] == "__qos0_callback__"):
                return
            _, callback, topic, payload = head
            self._tx_queue.popleft()
            if callback is not None:
                callback(topic, payload)
            self.on_publish(topic, payload)

    def _send_raw(self, payload):
        # Returns bytes sent, or 0 on EAGAIN.
        try:
            return self._socket.send(payload)
        except OSError as error:
            if error.errno == errno.EAGAIN:  # pragma: no cover - EAGAIN handling
                return 0
            raise

    def _enqueue_user_tx(self, *items):
        # Append user items as a unit under the user cap, raising
        # MQTTBackpressureError if they don't all fit (so a QoS-0 packet and its
        # callback marker can't half-land). Protocol packets bypass this cap via
        # _enqueue_internal_tx, since dropping them would break QoS-1/keepalive.
        if len(self._tx_queue) + len(items) > self._max_tx_queue_size:
            raise MQTTBackpressureError(
                f"tx queue full ({len(self._tx_queue)} + {len(items)} > "
                f"{self._max_tx_queue_size}); call handle() to drain "
                "and retry",
            )
        for item in items:
            self._tx_queue.append(item)

    def _enqueue_internal_tx(self, packet, *, front=False):
        # Queue a protocol packet in the headroom above the user cap. Returns
        # True when queued; at the hard cap it returns False and the caller
        # decides (retransmit/PINGREQ retry next tick; the PUBACK flush faults).
        # front=True queues ahead of user packets (a PUBACK the broker awaits).
        if len(self._tx_queue) >= self._tx_queue_hard_cap:
            return False
        if front:
            self._tx_queue.appendleft(packet)
        else:
            self._tx_queue.append(packet)
        return True

    # ------------------------------------------------------------------
    # Internal: RX path
    # ------------------------------------------------------------------

    def _recv_suppressed(self):
        # True while a PUBACK batch is queued unsent or a partial send is
        # pending: the socket isn't draining as fast as the broker fills, so
        # pausing recv leaves the bytes in the kernel buffer, closes the TCP
        # window, and throttles the broker while our memory stays bounded.
        return self._puback_batch_queued or self._partial_send is not None

    def _read_inbound(self, now_ms):
        # One recv_into per tick (the costly syscall that yields to the runner),
        # then dispatch ALL complete packets already buffered (parsing is cheap,
        # and no wake event may fire again until keepalive). The recv is capped
        # at recv_budget_per_tick. Skipped while _recv_suppressed so acks don't
        # pile up and cross-tick PUBACKs stay in receipt order.
        if self._recv_suppressed():
            return
        buffer_view = self._decoder.fill_buffer()
        capacity = self._decoder.fill_capacity()
        if capacity > self._recv_budget_per_tick:
            capacity = self._recv_budget_per_tick
            buffer_view = buffer_view[:capacity]
        if capacity > 0:
            try:
                got = self._socket.recv_into(buffer_view, capacity)
            except OSError as error:
                if error.errno == errno.EAGAIN:  # pragma: no cover - EAGAIN handling
                    got = 0  # No bytes this tick; fall through to dispatch.
                else:
                    raise
            else:
                if got == 0:
                    # recv_into returning 0 is a clean peer FIN (no-data raises
                    # EAGAIN, handled above). Raise so handle() faults to FAILED.
                    raise MQTTProtocolError("broker closed connection")
                self._decoder.advance(got)

        # Collect this tick's PUBACKs and flush them after dispatch as one
        # coalesced batch, in receipt order (MQTT-4.6.0-2). Reuse the instance
        # list instead of a fresh literal each tick.
        pending_pubacks = self._pending_pubacks
        pending_pubacks.clear()
        while True:
            packet = self._decoder.read_next()
            if packet is None:
                break
            if isinstance(packet, ParsedPublish):
                self._handle_inbound_publish(packet, pending_pubacks)
            elif isinstance(packet, _OversizedMessage):
                self._handle_oversized(packet, pending_pubacks)
            elif isinstance(packet, ParsedAck):
                self._handle_ack(packet, now_ms)
            # An inbound callback may have called disconnect(): stop
            # dispatching and don't re-queue anything.
            if self.state != ProtocolState.CONNECTED:
                return
        # Coalesce the tick's PUBACKs into ONE front-of-queue entry flushed
        # without the packet budget, so the ack rate tracks the dispatch rate.
        # A queue at the hard cap faults instead of dropping: losing a PUBACK
        # corrupts the stream, while a FAILED transition lets self-heal rebuild
        # and the broker redeliver.
        if pending_pubacks:
            if len(pending_pubacks) == 1:
                batch = pending_pubacks[0]
            else:
                batch = b"".join(pending_pubacks)
            if not self._enqueue_internal_tx(batch, front=True):
                raise MQTTError(
                    f"PUBACK backlog overflowed the tx queue hard cap "
                    f"({self._tx_queue_hard_cap}): protocol headroom "
                    "exhausted; reconnecting rather than dropping "
                    "protocol packets",
                )
            self._puback_batch_queued = True
        # Drop the just-enqueued references promptly.
        pending_pubacks.clear()

    def _handle_inbound_publish(self, packet, pending_pubacks):
        if self._inbound_queue is not None:
            # next_message() owns data delivery: queue, don't dispatch.
            self._inbound_queue.append(
                InboundPublish(packet.topic, packet.payload),
            )
        else:
            self.on_message(packet.topic, packet.payload)
        if packet.qos == 1:
            pending_pubacks.append(encode_puback(packet_id=packet.packet_id))

    def _handle_oversized(self, packet, pending_pubacks):
        if self._when_oversized == WhenOversized.DROP_SILENT:
            pass  # Drop without notification.
        elif self._when_oversized == WhenOversized.DROP_WITH_EVENT:
            self.on_oversized(packet.reported_length, packet.topic)
        elif self._when_oversized == WhenOversized.DISCONNECT:
            raise MQTTProtocolError(
                f"oversized message on topic {packet.topic!r} "
                f"({packet.reported_length} bytes)",
            )
        # PUBACK a QoS-1 oversize even when dropping the payload so the broker
        # stops retransmitting, but only when packet_id survived: an oversize
        # topic prelude yields packet_id=None, which encode_puback can't pack,
        # so skip the ack and let the broker redeliver.
        if (
            packet.qos == 1
            and packet.packet_id is not None
            and self._when_oversized != WhenOversized.DISCONNECT
        ):
            pending_pubacks.append(encode_puback(packet_id=packet.packet_id))

    def _handle_ack(self, packet, now_ms):
        # Match an ack to its pending entry. An unmatched PUBACK/SUBACK/UNSUBACK
        # faults to FAILED (the broker acked an id we never issued); a stray
        # PINGRESP is racy and tolerated.
        if packet.packet_type == PACKET_CONNACK:
            self._handle_connack(packet, now_ms)
            return
        if packet.packet_type == PACKET_PINGRESP:
            self._discard_pending(_AWAIT_PINGRESP, packet_id=None)
            return
        if packet.packet_type == PACKET_PUBACK:
            in_flight = self._in_flight.pop(packet.packet_id, None)
            if in_flight is None:
                # No pending entry: usually a duplicate PUBACK (broker acked
                # both our publish and its DUP retransmit). Tolerate it rather
                # than tearing down the session the retry exists to protect.
                return
            if in_flight.callback is not None:
                in_flight.callback()
            return
        if packet.packet_type == PACKET_SUBACK:
            # MQTT 3.1.1 §3.9.3: a granted_qos byte of 0x80 means "Failure"
            # (broker rejected the filter). Surface it as a protocol error
            # rather than silently inheriting a never-matched subscription.
            if packet.granted_qos and 0x80 in packet.granted_qos:
                # Evict the rejected filter before faulting so the self-heal
                # replay doesn't re-issue it and re-earn the rejection forever.
                self._evict_rejected_subscription(packet.packet_id)
                raise MQTTProtocolError(
                    f"SUBACK rejection (packet_id {packet.packet_id}, "
                    f"granted_qos {packet.granted_qos}); broker refused "
                    "one or more subscription filters"
                )
            matched = self._discard_pending(
                _AWAIT_SUBACK, packet_id=packet.packet_id,
            )
            if matched is None:
                raise MQTTProtocolError(
                    f"SUBACK for unknown packet_id {packet.packet_id}",
                )
            # The matched pending entry supplies the topic, keying the
            # desired-set entry whose second slot holds the one-shot
            # on_subscribe. Fire and clear it on the first grant; a no-op
            # afterward, so self-heal replays stay callback-silent.
            entry = self._subscriptions.get(matched.topic)
            if entry is not None and entry[1] is not None:
                callback = entry[1]
                entry[1] = None
                callback(packet.granted_qos)
            return
        if packet.packet_type == PACKET_UNSUBACK:
            matched = self._discard_pending(
                _AWAIT_UNSUBACK, packet_id=packet.packet_id, callback_arg=None,
            )
            if not matched:
                raise MQTTProtocolError(
                    f"UNSUBACK for unknown packet_id {packet.packet_id}",
                )
            return

    def _handle_connack(self, packet, now_ms):
        # CONNACK return-code 0 is success, anything else is failure.
        self._discard_pending(_AWAIT_CONNACK, packet_id=None)
        if packet.return_code != 0:
            # Rejection codes a broker may send (MQTT 3.1.1 §3.2.2.3). Built
            # inline so the dict only allocates on the rare rejection path.
            reason = {
                1: "unacceptable protocol version",
                2: "identifier rejected",
                3: "server unavailable",
                4: "bad username or password",
                5: "not authorized",
            }.get(packet.return_code)
            if reason is None:
                message = f"broker rejected CONNECT (return code {packet.return_code})"
            else:
                message = (
                    f"broker rejected CONNECT (return code {packet.return_code}: "
                    f"{reason})"
                )
            self.last_error = MQTTConnectError(message, return_code=packet.return_code)
            # Codes 1/2/4/5 can't be fixed by reconnecting, so latch permanent
            # failure; code 3 (server unavailable) stays transient.
            if packet.return_code in _PERMANENT_CONNACK_CODES:
                self._permanent_failure = True
            self.state = ProtocolState.FAILED
            return
        self.state = ProtocolState.CONNECTED
        # Reconnect succeeded: clear the self-heal backoff schedule so a
        # later transient drop starts its backoff fresh.
        self._self_heal_attempts = 0
        self._self_heal_retry_at_ticks = None
        self._next_ping_due_ticks = self._deadline(self._ping_interval_ms, now_ms=now_ms)
        # Session honesty: with clean_session=False and session-present=1 the
        # broker resumed our session, so its subscriptions still live and
        # replay is wasted; otherwise the broker forgot, so replay to restore
        # the inbound stream. The in-flight table is already kept across such a
        # reconnect, so this completes the resume.
        if self._clean_session or not packet.session_present:
            self._replay_subscriptions()
        # Flush publishes buffered before this CONNACK, oldest first and
        # ahead of any publish the on_connect callback issues.
        self._drain_pre_connect_queue()
        self.on_connect()

    def _replay_subscriptions(self):
        # Re-issue SUBSCRIBE for every desired subscription. Runs on each
        # successful CONNACK (gated by _handle_connack): it puts a pre-connect
        # declaration on the wire and restores the stream after a self-heal.
        # The per-topic on_subscribe fires only via each entry's one-shot, so a
        # self-heal replay stays silent.
        if not self._subscriptions:
            return
        for topic, entry in self._subscriptions.items():
            qos = entry[0]
            packet_id = self._allocate_packet_id()
            packet = encode_subscribe(
                packet_id=packet_id, subscriptions=[(topic, qos)],
            )
            # Route through the headroom, not the user cap: _enqueue_user_tx
            # would raise MQTTBackpressureError once subscriptions exceed the
            # cap, faulting into a reconnect-replay loop that never reconnects.
            self._enqueue_internal_tx(packet)
            self._pending_responses.append(
                PendingResponse(
                    awaiting=_AWAIT_SUBACK,
                    deadline_ticks=self._deadline(self._ack_timeout_ms),
                    packet_id=packet_id,
                    callback=None,
                    topic=topic,
                ),
            )

    def _evict_rejected_subscription(self, packet_id):
        # A SUBACK carries only the id, so recover the topic from the pending
        # entry and drop it so it is never replayed. No-op if absent.
        for pending in self._pending_responses:
            if pending.awaiting == _AWAIT_SUBACK and pending.packet_id == packet_id:
                if pending.topic is not None:
                    self._subscriptions.pop(pending.topic, None)
                return

    def _discard_pending(self, awaiting, *, packet_id, callback_arg=None):
        # Remove the matching PendingResponse and fire its callback; returns it
        # (truthy, so the SUBACK caller can read its topic) or None when no
        # match (the caller decides fault vs tolerated late arrival).
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
            return pending
        return None

    # ------------------------------------------------------------------
    # Internal: deadlines + keepalive
    # ------------------------------------------------------------------

    def _check_deadlines(self, now_ms):
        # Retry or fault on expired in-flight and pending entries. Neither loop
        # copies its collection: the paths that mutate it return immediately,
        # so the iterator never sees the change (steady-state zero allocation).
        for entry in self._in_flight.values():
            if self._ticks.ticks_diff(entry.deadline_ticks, now_ms) > 0:
                continue
            if entry.retry_count >= self._publish_retry_max:
                self._in_flight.pop(entry.packet_id, None)
                self.last_error = MQTTError(
                    f"PUBLISH packet_id {entry.packet_id} exceeded "
                    f"retry limit {self._publish_retry_max}",
                )
                self.state = ProtocolState.FAILED
                return
            # The DUP-flagged retransmit (bit 3 of byte 0, MQTT 3.1.1 §4.3.2)
            # is identical every retry, so build it once and reuse it.
            if entry.dup_packet_bytes is None:
                dup_packet = bytearray(entry.packet_bytes)
                dup_packet[0] |= 0x08
                entry.dup_packet_bytes = bytes(dup_packet)
            # Headroom may be full when many publishes are overdue: leave this
            # entry's deadline so it retries next tick without burning a retry.
            if not self._enqueue_internal_tx(entry.dup_packet_bytes):
                continue
            entry.retry_count += 1
            entry.deadline_ticks = self._deadline(self._ack_timeout_ms, now_ms=now_ms)

        for pending in self._pending_responses:
            if self._ticks.ticks_diff(pending.deadline_ticks, now_ms) > 0:
                continue
            self._pending_responses.remove(pending)
            self.last_error = MQTTError(
                f"timed out awaiting {pending.awaiting}",
            )
            self.state = ProtocolState.FAILED
            return

        # Send timeout: fires only when the deadline is armed (queue non-empty
        # or partial send pending) and a drain made no progress for send_timeout_ms.
        if self._send_deadline_ticks is not None:
            if self._ticks.ticks_diff(self._send_deadline_ticks, now_ms) <= 0:
                self.last_error = MQTTError(
                    "send timeout: tx queue made no progress for "
                    f"{self._send_timeout_ms} ms",
                )
                self.state = ProtocolState.FAILED
                return

    def _check_keepalive(self, now_ms):
        # Send a PINGREQ when half the keepalive interval has elapsed.
        if not self._keepalive_enabled:
            return  # keep_alive_seconds == 0: keepalive disabled.
        if self.state != ProtocolState.CONNECTED:
            return
        if self._ticks.ticks_diff(self._next_ping_due_ticks, now_ms) > 0:
            return
        # Already awaiting a PINGRESP?  Don't double-send.
        for pending in self._pending_responses:
            if pending.awaiting == _AWAIT_PINGRESP:
                return
        if not self._enqueue_internal_tx(PACKET_PINGREQ):
            return  # Headroom full; retry the ping next tick.
        self._pending_responses.append(
            PendingResponse(
                awaiting=_AWAIT_PINGRESP,
                deadline_ticks=self._deadline(self._ack_timeout_ms, now_ms=now_ms),
            ),
        )
        self._next_ping_due_ticks = self._deadline(self._ping_interval_ms, now_ms=now_ms)

    def _deadline(self, offset_ms, *, now_ms=None):
        # Tick value offset_ms in the future. Pass now_ms inside the tick loop
        # so every deadline armed that tick shares one ticks_ms() reading.
        if now_ms is None:
            now_ms = self._ticks.ticks_ms()
        return self._ticks.ticks_add(now_ms, offset_ms)
