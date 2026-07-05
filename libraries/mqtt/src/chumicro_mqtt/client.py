"""MQTT 3.1.1 client built on chumicro-sockets + chumicro-timing.

:class:`MQTTClient` is the entry point.  No threads, no async:
cooperative dispatch in the caller's tick loop.

The connection-state classes (:class:`ProtocolState`,
:class:`PendingResponse`, :class:`InFlightPublish`) live here.
The wire-format primitives live in :mod:`chumicro_mqtt._wire`.

In-flight QoS-1 PUBLISHes are held in ``MQTTClient._in_flight``, a
plain ``dict[int, InFlightPublish]`` keyed by packet-id.  Allocation
goes through :meth:`MQTTClient._allocate_packet_id`, which handles
1-65535 wraparound and refuses ids already in flight.
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

# Poll-interest bits for ``io_interest``; mirror ``chumicro_runner.IO_READ``
# / ``IO_WRITE`` by value.  Held as literals rather than imported so the
# MQTT client takes no dependency edge on the runner — a client runs
# without a runner (bring-your-own-scheduler / duck typing).
_IO_READ = 1
_IO_WRITE = 2

# ---------------------------------------------------------------------------
# Connection state + pending-work tracking
# ---------------------------------------------------------------------------


class ProtocolState:
    """Connection lifecycle states.

    Transitions monotonically forward except after a fault::

      DISCONNECTED -> AWAITING_TRANSPORT -> CONNECTING -> CONNECTED
                                                       \\-> FAILED -> AWAITING_TRANSPORT (self-heal)
                                                                   -> DISCONNECTED
                                          CONNECTED -> DISCONNECTED

    ``AWAITING_TRANSPORT`` is when the underlying socket is being
    brought up across multiple ticks by a :class:`SocketConnector`
    (DNS / TCP / TLS handshake).  ``CONNECTING`` is the MQTT-protocol
    phase: socket is up, CONNECT has been queued, waiting for CONNACK.
    A client built with a pre-connected socket skips ``AWAITING_TRANSPORT``
    and starts at ``CONNECTING`` directly.

    ``disconnect()`` is synchronous (DISCONNECT packet + close), so there
    is no intermediate "disconnecting" state to observe.
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
    """Resume-every-tick wait yielded by ``next_message`` while the queue is empty."""

    # Of the duck-typed wait protocol chumicro_sockets.waits describes, this
    # carries only io_socket, pinned to None: the client is registered with
    # the runner in its own right and owns the socket poll, so the generator
    # just re-checks the queue each tick.

    io_socket = None


_INBOUND_WAIT = _InboundWait()


# Tags identifying which broker response a pending work-item expects.
# Module-level so the import allocates 5 small string bindings instead
# of a class object + its type machinery (~5-7 fewer small heap pins
# on Pi Pico W MP).  Underscore-prefixed: not re-exported.
_AWAIT_CONNACK = "connack"
_AWAIT_PINGRESP = "pingresp"
_AWAIT_PUBACK = "puback"
_AWAIT_SUBACK = "suback"
_AWAIT_UNSUBACK = "unsuback"

# Self-heal reconnect backoff.  A FAILED client with a transport_factory
# rebuilds the transport, but retrying every tick storms the broker and
# drains battery on a persistent failure (dead wifi, unreachable host).
# The first retry after a fresh failure is immediate; each subsequent
# retry doubles the wait from _SELF_HEAL_BACKOFF_BASE_MS up to
# _SELF_HEAL_BACKOFF_CAP_MS.  A successful CONNACK resets the schedule.
_SELF_HEAL_BACKOFF_BASE_MS = 1000
_SELF_HEAL_BACKOFF_CAP_MS = 60000

# CONNACK return codes that no amount of retrying can fix: unacceptable
# protocol version (1), identifier rejected (2), bad username/password
# (4), not authorized (5).  Reconnecting with the same CONNECT packet
# would just re-earn the same rejection, so the client stops self-healing
# and stays FAILED.  Code 3 (server unavailable) is transient and keeps
# retrying with backoff.
_PERMANENT_CONNACK_CODES = (1, 2, 4, 5)

# Bound on the ``next_message()`` inbound queue (drop-oldest when full).
# A slow consumer loses the oldest queued messages rather than growing
# the heap; 16 absorbs a healthy burst while pinning trivial RAM.
_MAX_INBOUND_QUEUE_SIZE = 16


class InFlightPublish:
    """One outstanding QoS 1 PUBLISH awaiting a PUBACK.

    Carries the bytes ready to re-send (so we don't re-encode on
    retry), a retry counter, a deadline (ticks), and an optional
    callback that fires once on PUBACK.
    """

    def __init__(self, packet_id, packet_bytes, deadline_ticks, callback=None):
        self.packet_id = packet_id
        self.packet_bytes = packet_bytes
        self.retry_count = 0
        self.deadline_ticks = deadline_ticks
        self.callback = callback
        # The DUP-flagged retransmit bytes, identical across every retry
        # of this packet — built once on first retry and reused so a
        # retry doesn't re-copy packet_bytes each time.
        self.dup_packet_bytes = None


class PendingResponse:
    """A non-publish response (CONNACK / SUBACK / UNSUBACK / PINGRESP) we're waiting for.

    Each carries an ``_AWAIT_*`` tag, a deadline, an optional packet_id,
    and an optional callback that fires once on receipt.  Multiple
    pending responses can coexist: tracking is per-entry rather than
    via a single broad waiting-state lock.

    SUBACK entries also carry the subscribed ``topic`` so a rejection
    (granted_qos 0x80) can evict that filter from the client's
    subscription set before it faults.
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

    #: Default.  Drop the payload, fire ``on_oversized(reported_length, topic)``,
    #: still PUBACK so the broker doesn't retransmit.  ``topic`` is
    #: ``None`` when the inbound topic itself overflowed ``rx_buffer_size``
    #: (it was never decoded), so an ``on_oversized`` handler must guard
    #: before calling string methods on it.
    DROP_WITH_EVENT = "drop_with_event"

    #: Treat as a protocol error: disconnect.  Use when application
    #: invariants assume payloads fit within the configured cap.
    DISCONNECT = "disconnect"


def _no_callback(*_args, **_kwargs):
    """Default no-op callback so handlers can be stored unconditionally."""
    return None


def _new_tx_queue(maxlen):
    """Return a fresh outbound ``deque`` sized at *maxlen* with ``appendleft``.

    MicroPython and CircuitPython require ``flags=1`` as a third
    positional argument to enable ``appendleft`` (and other
    bidirectional ops).  CPython rejects the third arg with
    ``TypeError`` because its full-featured deque needs no flag.  Try
    the MP/CP shape first so embedded gets the cheaper path, then fall
    back to the 2-arg shape on CPython.

    """
    try:
        return deque((), maxlen, 1)
    except TypeError:  # CPython: 2-arg constructor, appendleft already supported.
        return deque((), maxlen)


def _force_non_blocking(socket):
    """Best-effort ``setblocking(False)``.  The tick-based RX path requires
    non-blocking recv, and MP plain TCP defaults to blocking.  Some MP
    TLS adapters lack ``setblocking`` entirely, so the ``getattr`` +
    ``try`` handles both shapes."""
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

        Reads ``mqtt.broker.host`` / ``mqtt.broker.port`` (required when
        no *socket* / *transport_factory* override), plus optional
        ``mqtt.client_id`` / ``mqtt.keep_alive_seconds`` / ``mqtt.username``
        / ``mqtt.password`` / ``mqtt.when_disconnected`` (the
        publish-before-connected policy, default ``"queue"``).  A
        *socket* or *transport_factory* override
        bypasses the auto-built factory entirely.  Missing broker keys
        raise :class:`chumicro_config.MissingConfigKey`.

        *ticks* forwards to the constructor's clock seam so tests can
        inject :class:`chumicro_timing.testing.FakeTicks` through this
        path too — every deadline the client arms (including at
        user-entry calls like :meth:`connect`) reads the injected
        clock, keeping fake-now `handle()` driving on a single clock.

        Raises:
            ValueError: *config* is not a mapping-like object (a raw
                ``None`` or a stray value gets a clear error here rather
                than a downstream ``TypeError`` / ``AttributeError``).
        """
        if not hasattr(config, "get"):
            raise ValueError(
                "from_config requires a mapping-like config "
                f"(RuntimeConfig or dict), got {type(config).__name__}",
            )
        if socket is None and transport_factory is None:
            # Lazy import so users who pass their own socket / transport_factory
            # don't pull chumicro_sockets into the deploy graph.  See
            # ``chumicro_mqtt.sockets_factory`` for the helper itself.
            try:
                from chumicro_mqtt.sockets_factory import (  # noqa: PLC0415 - lazy
                    chumicro_sockets_connector_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_mqtt.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or "
                    "not on the board) — pass transport_factory= or "
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
                ``recv_into`` / ``send`` / ``close`` / ``setblocking``.
                See the user guide's "Bring your own transport" table
                for the per-method contract.  The client takes
                ownership.  :meth:`disconnect` closes it.  May be
                ``None`` when *transport_factory* is provided.
            transport_factory: Optional zero-arg callable returning a
                :class:`~chumicro_sockets.SocketConnector` — the
                non-blocking connect state machine.  Used in two paths:
                (1) when *socket* is ``None``, :meth:`connect` invokes
                the factory to build the initial connector and enters
                ``AWAITING_TRANSPORT``; subsequent ``handle()`` ticks
                drive the connector through DNS / TCP / TLS without
                blocking the runner.  (2) when the client transitions
                to ``FAILED`` after a wifi-drop / socket-death, the
                next ``handle()`` builds a fresh connector and re-enters
                ``AWAITING_TRANSPORT``.  Without a factory, the caller
                must supply *socket* and manage reconnect themselves.
                Construction is always side-effect free: the factory
                only fires from ``connect()`` / self-heal, never from
                ``__init__``.
            client_id: MQTT client identifier.  Must be unique per broker.
            keep_alive_seconds: Broker idle timeout.  PINGREQ runs at
                half this interval client-side.
            ack_timeout_seconds: Per-PUBACK / SUBACK / etc. deadline.
                Triggers a retry (PUBLISH) or fault (everything else).
                Also bounds each connector-driven transport attempt
                (DNS + TCP + TLS bring-up) — see :meth:`connect`.
            publish_retry_max: Max QoS 1 PUBLISH retries before giving
                up + transitioning to FAILED.
            username: Optional auth username (paired with *password*).
            password: Optional auth password.
            clean_session: ``False`` resumes persistent broker session
                state for QoS 1+ retransmit-across-reconnects.
            will_topic: Topic for the broker's last-will message.
                Published on uncleanly-dropped connection.  ``None``
                disables the will.
            will_message: Payload for the broker's last-will message.
            will_qos: QoS for the will message (0 or 1).
            will_retain: ``True`` retains the will on the broker.
            rx_buffer_size: Steady-state RX buffer size (default 256).
                Inbound PUBLISHes whose total wire size is ≤ this size
                parse inline with no allocation and deliver to
                :attr:`on_message` with their full payload.  A PUBLISH
                larger than this routes through the oversized tier —
                the configured :class:`WhenOversized` policy applies
                and the payload is discarded via rolling drain without
                a payload-sized heap allocation.  Size this up to the
                largest PUBLISH a consumer needs to receive intact.
            when_oversized: Policy for inbound messages larger than
                ``rx_buffer_size``.  See :class:`WhenOversized`.
            when_disconnected: Policy for :meth:`publish` called before
                the client reaches ``CONNECTED`` (the async-connect and
                self-heal windows).  ``"queue"`` (default) buffers the
                publish in a small bounded queue drained on CONNACK —
                a full queue raises :class:`MQTTBackpressureError`, the
                same backpressure signal :meth:`publish` uses when the
                tx queue is full.  ``"raise"`` raises :class:`MQTTError`
                immediately (the pre-queue behavior).
            pre_connect_queue_size: Bound on the pre-connect publish
                queue (default 8).  The publish-when-connected sensor
                profile only queues a handful of messages during the
                connect / self-heal window, so a small bound absorbs a
                short burst while pinning trivial heap; raise it for a
                publisher that produces faster than it reconnects.
            recv_budget_per_tick: The inbound pacing lever: cap on the
                bytes the single per-tick ``recv_into`` pulls off the
                socket (default 1024).  Bounds three things at once —
                tick latency while a large inbound PUBLISH is
                mid-flight (concurrent runner tasks keep getting CPU
                time), the number of complete packets one tick can
                dispatch, and therefore the size of the per-tick
                coalesced PUBACK batch an inbound QoS-1 burst owes.
                Raise for a higher-throughput subscriber at the cost
                of per-tick latency.
            max_tx_queue_size: Maximum number of pending outbound
                packets (default 20).  Appending past the cap raises
                :class:`MQTTBackpressureError`.  Raise the cap for
                bursty publishers.
            send_timeout_seconds: Maximum time the socket can stay
                non-writable with a packet queued before the client
                transitions to ``FAILED``.  ``None`` (default) inherits
                ``ack_timeout_seconds``.  Re-arms every time a send
                makes progress, so a steady stream of small sends won't
                trip it; only a stalled socket does.  Self-heal fires
                on the next tick after the transition.
            ticks: Optional tick source.  Any object exposing
                ``ticks_ms``, ``ticks_diff``, ``ticks_add`` (matches
                the ``chumicro_timing.ticks`` submodule shape).
                Defaults to that submodule (real clock).  Tests pass
                ``FakeTicks`` from ``chumicro_timing.testing``.
        """
        if socket is None and transport_factory is None:
            raise ValueError(
                "MQTTClient requires either a connected socket or a "
                "transport_factory (or both — factory is used for self-heal "
                "after wifi-drop)."
            )
        self._socket = socket
        self._transport_factory = transport_factory
        self._connector = None
        # Overall deadline for the in-flight transport attempt.
        # Connectors never time out on their own (their ``next_deadline``
        # is ``None`` by design — the consumer owns the deadline), so a
        # black-holed TCP connect or stalled TLS handshake would park in
        # ``AWAITING_TRANSPORT`` forever without this.  Armed whenever a
        # connector is built (``connect()`` / self-heal) with the
        # ``ack_timeout_seconds`` window; cleared when the connector
        # reaches a terminal state or is cancelled.
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
        # Publishes issued before CONNECTED (async-connect + self-heal
        # windows) buffer here under the "queue" policy, then drain on
        # CONNACK in receipt order ahead of any publish the
        # ``on_connect`` callback issues.  A plain deque used FIFO
        # (append / popleft); bounds are enforced explicitly in
        # ``_publish_disconnected`` so overflow never relies on the
        # deque's own (raise-on-MP / silent-drop-on-CPython) behavior.
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
        # In-flight QoS-1 PUBLISHes keyed by packet-id.  Allocation
        # goes through ``_allocate_packet_id`` (wraparound +
        # collision-avoidance); the dict itself holds the entries.
        self._in_flight = {}
        self._next_packet_id = 1
        self._pending_responses = []
        # The desired subscription set: topic (post-prefixing) →
        # ``[requested_qos, pending_on_subscribe]``.  A two-item list
        # (not a class — allocation-light) whose second slot holds a
        # one-shot ``on_subscribe`` callback that fires on the FIRST
        # SUBACK granting the topic, then clears to ``None``.  Eagerly
        # maintained by :meth:`subscribe` / :meth:`unsubscribe` so it
        # always reflects "what the user wants subscribed right now" —
        # a :meth:`subscribe` call is a DECLARATION valid in any state,
        # not just CONNECTED.  Replayed on every CONNACK that lands in
        # CONNECTED (:meth:`_replay_subscriptions`) so a pre-connect
        # declaration reaches the wire on the first connect and a
        # self-heal reconnect restores the inbound stream — a broker
        # with clean_session=True forgets subscriptions across
        # reconnects, and with clean_session=False the session-present
        # gate skips the (then-redundant) replay.
        self._subscriptions = {}
        # 64-slot headroom above the user cap so the QoS-1 retry path
        # and PINGREQ can't silently lose protocol packets when the
        # queue is at the user cap.  ``_enqueue_user_tx`` enforces the
        # user cap; ``_enqueue_internal_tx`` checks this structural
        # bound explicitly so a flood never relies on the deque's
        # overflow (which raises on MP/CP and silently evicts on CPython).
        self._tx_queue_hard_cap = max_tx_queue_size + 64
        self._tx_queue = _new_tx_queue(self._tx_queue_hard_cap)
        self._partial_send = None  # (memoryview, offset) when last send was short.
        # Reused across recv ticks so the common QoS-0 subscriber (no
        # PUBACKs to collect) doesn't allocate a fresh list literal on
        # every ``_read_inbound``.  Emptied at the start of each tick's
        # collection so a mid-dispatch disconnect that drops collected
        # PUBACKs leaves nothing to re-flush next tick.
        self._pending_pubacks = []
        # True while a coalesced PUBACK batch (one tick's inbound QoS-1
        # acks joined into a single tx entry) is still queued unsent.
        # Gates the next recv: reading faster than we can ack would
        # grow the ack backlog without bound, while leaving the bytes
        # in the kernel buffer closes the TCP window and throttles the
        # broker at its end.  See ``_recv_suppressed``.
        self._puback_batch_queued = False
        # Deadline-tick value while a packet has been queued without any
        # send progress.  ``None`` when the queue is empty or the last
        # drain made progress (a successful send re-arms; an EAGAIN
        # leaves the existing deadline ticking).  Surfaced via
        # ``next_deadline`` so the runner wakes by it.
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
        # Self-heal reconnect pacing.  ``_self_heal_attempts`` counts
        # consecutive failed reconnects (reset on a successful CONNACK);
        # ``_self_heal_retry_at_ticks`` gates the next attempt so FAILED
        # doesn't rebuild the transport every tick.  ``_permanent_failure``
        # latches on a CONNACK rejection code that retrying can't fix
        # (bad credentials, not authorized) so the client stops self-healing
        # entirely until the next explicit ``connect()``.
        self._self_heal_attempts = 0
        self._self_heal_retry_at_ticks = None
        self._permanent_failure = False
        # ``hold()`` latches this to suspend timer-driven reconnection
        # (a held FAILED client does not dial and parks); ``connect()``
        # releases it.
        self._reconnect_held = False

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def connect(self):
        """Express the intent "be connected", acting on it now.

        An intent, not a state-transition guard.  DISCONNECTED begins the
        connect sequence; FAILED is "self-heal now" (reset backoff, dial
        immediately via the same self-heal path a timer uses — identical
        queue fate, minus the residual backoff); CONNECTED / CONNECTING /
        AWAITING_TRANSPORT are an idempotent no-op.  Every state clears any
        :meth:`hold` and latches the intent.  See the guide.
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
        # satisfied — idempotent no-op beyond the hold clear above.

    def hold(self):
        """Suspend timer-driven reconnection until the next :meth:`connect`.

        The mate of intent-based :meth:`connect`, for when the app KNOWS
        the link is down (a self-heal timer dialing a dead radio wastes
        cycles).  A pure intent latch: no state change, no cancel of an
        in-flight dial.  While FAILED it suppresses self-heal — no dial,
        state stays FAILED with ``last_error`` kept, ``next_deadline``
        parks; publishes still buffer per ``when_disconnected``.  Set
        earlier it is dormant until the link faults to FAILED.
        ``connect()`` is the release.  See the guide for the wifi wiring.
        """
        self._reconnect_held = True

    def _enqueue_connect_packet(self):
        """Encode the CONNECT packet, append it to the tx queue, and
        arm the CONNACK pending-response slot.

        Called when the socket is already in hand — either at
        :meth:`connect` time with a pre-built socket, or once the
        connector reaches ``ready`` inside :meth:`handle`.
        """
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

        Idempotent: a second call against a client that's already in
        DISCONNECTED state is a no-op (no extra ``on_disconnect`` fire,
        no socket re-close).  From CONNECTED / CONNECTING, attempts a
        best-effort DISCONNECT packet on the wire and then closes.
        From AWAITING_TRANSPORT, cancels the in-flight connector
        (which closes any half-open socket); no DISCONNECT packet is
        attempted because the MQTT layer never came up.  From FAILED,
        the socket is likely dead so the DISCONNECT attempt is skipped;
        only the close + state transition happen.  ``on_disconnect``
        fires exactly once on the anything-to-DISCONNECTED transition.

        Best-effort: any exception during send/close is swallowed so
        the client always lands in a known DISCONNECTED state.
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
        # Null the socket and drop socket-bound state so a later
        # connect() routes through the connector factory instead of
        # re-arming CONNECT against the closed fd (which faulted every
        # reconnect), and so no stale queued packet or half-read inbound
        # packet survives the disconnect.
        self._socket = None
        self._reset_transient_state()
        # Drop any publishes queued for a connect that will never come
        # (the user explicitly parked).  Self-heal keeps the queue —
        # ``_reset_transient_state`` deliberately doesn't touch it — so
        # only a deliberate disconnect discards buffered publishes.
        self._pre_connect_queue = _new_tx_queue(self._pre_connect_queue_size)
        self.state = ProtocolState.DISCONNECTED
        self._user_wants_connected = False
        # A deliberate teardown drops every reconnect intent, including a
        # caller hold; a later connect() starts from a clean slate.
        self._reconnect_held = False
        self.on_disconnect()

    def _reset_transient_state(self):
        """Drop socket-bound tx / rx state so a fresh transport starts clean.

        A fresh tx queue (MicroPython / CircuitPython deque has no
        ``clear()``), no partial send, no armed send deadline, no
        pending responses, and a fresh decoder that discards any
        half-read inbound packet left on the old socket.
        """
        self._tx_queue = _new_tx_queue(self._tx_queue_hard_cap)
        self._partial_send = None
        self._puback_batch_queued = False
        self._send_deadline_ticks = None
        self._transport_deadline_ticks = None
        self._pending_responses.clear()
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

        Args:
            topic: Will topic.  ``None`` disables the will entirely.
            message: Will payload (bytes).  ``None`` becomes empty bytes.
            qos: Will QoS (0 or 1).
            retain: ``True`` retains the will on the broker.

        The change applies to the next CONNECT packet the client
        sends -- either an initial :meth:`connect` or a self-heal
        reconnect after FAILED.  The current connection already
        registered its will with the broker at CONNECT time and
        cannot be modified in flight.

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
        """Apply the ``when_disconnected`` policy to a pre-CONNECTED publish.

        ``"raise"`` reproduces the pre-queue behavior exactly.  ``"queue"``
        appends the resolved publish (payload already bytes) to the
        bounded pre-connect queue for :meth:`_drain_pre_connect_queue`
        to replay on CONNACK.  The bound is enforced explicitly with
        the same backpressure error a full tx queue raises.
        """
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
        """Flush queued pre-connect publishes onto the wire, oldest first.

        Runs on a successful CONNACK before ``on_connect`` fires, so
        buffered publishes reach the tx queue ahead of any publish the
        callback issues (receipt order preserved).  Each entry carries
        its resolved topic / payload / qos / retain / on_publish.
        """
        queue = self._pre_connect_queue
        while queue:
            topic, payload_bytes, qos, retain, on_publish = queue.popleft()
            self._do_publish(topic, payload_bytes, qos, retain, on_publish)

    def _do_publish(self, topic, payload_bytes, qos, retain, on_publish):
        """Encode and enqueue a resolved PUBLISH (caller is CONNECTED).

        *payload_bytes* is already encoded.  Shared by the direct
        :meth:`publish` path and the pre-connect drain.
        """
        if qos == 0:
            packet = encode_publish(
                topic=topic, payload=payload_bytes, qos=0, retain=retain,
            )
            # QoS 0 has no ack, so a callback fires once the bytes hit the
            # wire via a marker entry.  Packet + marker enqueue as one
            # capacity-checked unit so the pair can't half-land or slip
            # the cap an item at a time (each pins payload_bytes, so both
            # count).  No callback wired: single-slot fast path.
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

        # ``_allocate_packet_id`` already refuses ids already in the
        # in-flight table, so this assignment never overwrites a live
        # entry — assert defensively so a future refactor doesn't lose
        # the invariant silently.
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
        """Declare a subscription for *topic* — valid in any state.

        A declaration, not a wire command: it records *topic* in the
        desired subscription set.  When already ``CONNECTED`` the
        SUBSCRIBE also goes on the wire now (unchanged behavior); in any
        other state (pre-connect, self-heal outage, or after
        ``disconnect()``) no traffic happens now and the first CONNACK's
        replay path (:meth:`_replay_subscriptions`) sends it.  So a
        device can declare its subscriptions once at startup instead of
        threading them through ``on_connect``.  No state is rejected: a
        later :meth:`connect` always resets a ``FAILED`` / ``DISCONNECTED``
        client, so any declaration can eventually reach the wire.

        Args:
            topic: Topic filter (``+`` / ``#`` wildcards ok), on the
                wire as written.
            qos: 0 or 1.
            on_subscribe: One-shot ``(topic, granted_qos)`` fired on the
                FIRST SUBACK granting *topic* — direct send or replay —
                then cleared, so self-heal replays stay silent.

        Raises:
            MQTTBackpressureError: already CONNECTED and the tx queue is
                full (only the direct-send path touches the tx queue).
        """
        def _wrapped(granted_qos):
            if on_subscribe is not None:
                on_subscribe(topic, granted_qos)
            self.on_subscribe(topic, granted_qos)

        # CONNECTED: send now, before recording the entry, so a full-queue
        # backpressure error leaves the desired-set untouched (byte-for-byte
        # the pre-declarative CONNECTED path).  The SUBACK callback lives
        # with the entry (its second slot), not the PendingResponse, so the
        # direct send and a replay share one firing path (the SUBACK branch
        # of _handle_ack fires and clears it).
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
        """Retract a subscription for *topic* — valid in any state.

        Mirror of :meth:`subscribe`: *topic* goes on the wire as
        written.  Always drops *topic* from the desired set so a replay
        never re-issues it.  When ``CONNECTED`` also sends the
        UNSUBSCRIBE and fires *on_unsubscribe* on the UNSUBACK; otherwise
        it just retracts the declaration (nothing is on the wire yet).
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

        The first call switches inbound data delivery from the
        ``on_message`` callback to a bounded queue this drains;
        lifecycle callbacks (``on_connect`` /
        ``on_disconnect`` / ``on_oversized``) keep firing either way.
        Returns an :class:`InboundPublish` while the queue holds one —
        draining queued messages even after a disconnect — then
        ``None`` once the client is parked for good (deliberate
        ``disconnect()``, or FAILED with no self-heal possible) and the
        queue is empty.  Transient FAILED states keep the generator
        suspended: self-heal may resume the stream.

        The queue is bounded at 16 messages (drop-oldest when full): a
        consumer that falls behind silently loses the oldest queued
        messages rather than growing the heap.  This is the
        receive-stream flavor for single-subscription consumers;
        multi-topic fan-out stays on the callbacks — pick one surface
        per client, not both.
        """
        if self._inbound_queue is None:
            # 2-arg deque (no overflow-check flag) drops the oldest item
            # on append-when-full on every runtime — CPython via maxlen,
            # MicroPython / CircuitPython via the default flags=0.  (The
            # TX queue raises instead, for backpressure.)
            self._inbound_queue = deque((), _MAX_INBOUND_QUEUE_SIZE)
        while True:
            if self._inbound_queue:
                return self._inbound_queue.popleft()
            if self._inbound_stream_ended():
                return None
            yield _INBOUND_WAIT

    def _inbound_stream_ended(self):
        """Whether the client can never deliver another inbound PUBLISH.

        Mirrors ``next_deadline``'s parked-forever condition: a
        deliberate disconnect, or FAILED with self-heal impossible
        (permanent failure, no connector factory, or the user never
        asked to be connected).  A :meth:`hold` is not stream-ending — it
        is releasable, so the stream is only suspended.
        """
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

        The recv path is cooperative: ``handle()`` always attempts a
        non-blocking recv and bails on EAGAIN, so any non-terminal
        state is worth a tick.  ``FAILED`` qualifies — ``handle()``'s
        FAILED branch is where ``_attempt_self_heal`` lives, and that
        has to keep firing until the broker is reachable again.
        ``DISCONNECTED`` (a terminal state), a permanently-failed client
        (a CONNACK rejection no reconnect can fix), and one held by
        :meth:`hold` are gated out — none has handle work left until a
        ``connect()``.
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
        """The MQTT socket-ish object while connected, connecting, or
        bringing up transport, else ``None``.

        While in ``AWAITING_TRANSPORT`` this forwards to the connector's
        in-flight pollable so ``Runner.wait`` parks correctly between
        connect phases.  While in ``CONNECTING`` / ``CONNECTED`` it
        returns the MQTT socket as-is; the runner unwraps any ``.sock``
        adapter wrapper at the poller.  ``DISCONNECTED`` and ``FAILED``
        return ``None`` so the runner does not wake on a dead handle.
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

        The read bit is set while ``handle()`` would consume inbound
        bytes; the write bit while outbound bytes are queued (or a
        connect phase needs writability).

        Live MQTT connections (``CONNECTING`` / ``CONNECTED``) want
        read — brokers send CONNACK / SUBACK / PUBACK / PINGRESP /
        inbound PUBLISH at any time — except while the recv is
        suppressed for outbound backpressure (see
        :meth:`_recv_suppressed`): a suppressed tick skips its recv,
        so asking to be woken for readability would just spin the
        runner against bytes this client refuses to read.
        ``AWAITING_TRANSPORT`` forwards to the connector (only its
        TLS-handshake phase wants read; its TCP-connect phase wants
        write).

        A partial send (an EAGAIN mid-packet) has no queue entry but
        still needs writability: without this the runner never registers
        POLLOUT, the send never resumes, and the stalled packet trips
        the send timeout instead.
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

        Called by ``Runner.wait`` when ``ipoll`` reports an error or
        hangup on the socket this client registered.  Transitions to
        ``FAILED`` with ``last_error`` describing the event, so the
        next ``handle()`` tick fires self-heal (build a fresh connector,
        re-enter AWAITING_TRANSPORT).  When the error fires during
        AWAITING_TRANSPORT, the in-flight connector is cancelled before
        the FAILED transition.
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

        Returns the minimum across the keepalive timer
        (``_next_ping_due_ticks`` while connected), each pending
        response's ack deadline, each in-flight QoS 1 publish's retry
        deadline, and the send timeout (when armed).  ``None`` when no
        deadline applies (the runner falls back to the next periodic-
        task ``next_due_ms``).

        While ``AWAITING_TRANSPORT`` with no pollable yet (the connector
        is still resolving DNS, so ``io_socket`` is ``None`` and
        ``Runner.wait`` has nothing to park on), this returns *now_ms* —
        an immediate deadline that keeps the loop ticking the
        tick-driven connector forward.  Once a pollable exists
        (TCP-connect onward) the runner parks on handshake progress,
        bounded by the transport-attempt deadline (connectors carry no
        deadline of their own — the client owns the attempt window).
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
            # A self-heal-active FAILED client wakes at its next backoff
            # retry — or immediately when no backoff is armed yet (the
            # first attempt after a fresh failure, or a connect()-forced
            # reset), so the runner ticks self-heal instead of parking on
            # some other service's socket.  A permanent failure, no
            # factory, or a caller hold parks forever (until connect()).
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

        Checks ack deadlines + keepalive timer first (so a wedged recv
        can't block timeout detection), then pulls inbound bytes into
        the decoder and processes any complete packets (PUBACKs free
        in-flight slots and inbound QoS-1 publishes coalesce their
        PUBACKs into one front-of-queue batch), then drains the TX
        queue (flushes the PUBACK batch outside the per-tick send
        budget, then sends one packet — a DUP retransmit or PINGREQ
        queued by the checks above, or an application packet enqueued
        between ticks).

        When the client is in ``FAILED`` and self-heal is active (see
        :meth:`_self_heal_active`), this tick attempts a self-heal: build
        a fresh connector and enter ``AWAITING_TRANSPORT``.  Subsequent
        ticks drive the connector through DNS / TCP / TLS without blocking
        the runner — the same path the initial :meth:`connect` takes, and
        the one ``connect()`` from FAILED re-arms.  Without a factory, or
        while held, the client stays in ``FAILED``.

        ``AWAITING_TRANSPORT`` ticks check the transport-attempt
        deadline first (deadlines before I/O), then call
        ``connector.tick(now_ms)``; when the connector reaches
        ``ready`` the socket is promoted, CONNECT is queued, and the
        state moves to ``CONNECTING``.  When the connector fails — or
        the attempt outlives its ``ack_timeout_seconds`` window — the
        state moves to ``FAILED`` with ``last_error`` carrying the
        cause, and self-heal schedules the next attempt.

        *now_ms* is the per-tick timestamp the runner captured once
        and passes to every registered service so they all see the
        same instant (the runner contract).  Callers must source it
        from ``chumicro_timing.ticks_ms()`` (or the matching method on
        the injected ``ticks`` object) so the value is in the same
        domain as the deadlines this client computed at ``connect()`` /
        ``publish()`` time.  ``chumicro-runner.Runner`` handles this
        automatically.  Tests that roll their own poll loops must do
        the same.
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
            # Self-heal succeeded — state is AWAITING_TRANSPORT.  Fall
            # through to the connector-advance branch this same tick so
            # the connector gets one tick of progress immediately.
        if self.state == ProtocolState.AWAITING_TRANSPORT:
            # Deadline before I/O, same as the connected-path ordering:
            # a stalled attempt faults here without giving the connector
            # another tick.
            if self._check_transport_deadline(now_ms):
                return
            if not self._advance_connector(now_ms):
                return
            # Connector reached ready — state is CONNECTING with the
            # CONNECT packet queued.  Fall through to drain it.
        if self.state == ProtocolState.DISCONNECTED:
            return
        try:
            # Order: timeouts first so a wedged recv can't block deadline
            # detection.  Then read (PUBACKs free in-flight slots and
            # the tick's PUBACK-for-inbound batch is queued).  Then drain
            # (flushes the PUBACK batch budget-free, then sends one
            # packet: a DUP retransmit or PINGREQ queued by the checks
            # above, or an application packet enqueued between ticks).
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
        """Whether a FAILED client will (re)dial its transport on its own.

        ``True`` only with a factory, the caller asking to connect, no
        permanent CONNACK rejection, and no caller :meth:`hold`.  The
        ``handle()`` self-heal branch and ``next_deadline``'s FAILED wake
        both gate on this, keeping the dial and its scheduling in lockstep.
        """
        return (
            self._transport_factory is not None
            and self._user_wants_connected
            and not self._permanent_failure
            and not self._reconnect_held
        )

    def _arm_self_heal_backoff(self, now_ms):
        """Schedule the earliest tick the next self-heal attempt may run.

        Doubles the wait from ``_SELF_HEAL_BACKOFF_BASE_MS`` per
        consecutive attempt, capped at ``_SELF_HEAL_BACKOFF_CAP_MS``.
        Called just before each attempt, so the current attempt runs now
        and only a *subsequent* FAILED tick is gated.  A successful
        CONNACK zeroes ``_self_heal_attempts`` and clears the deadline.
        """
        # Clamp the shift so a multi-hour outage doesn't grow an
        # ever-larger big-int before the cap clips it (6 doublings of a
        # 1 s base already exceeds the 60 s cap).
        if self._self_heal_attempts >= 6:
            delay_ms = _SELF_HEAL_BACKOFF_CAP_MS
        else:
            delay_ms = _SELF_HEAL_BACKOFF_BASE_MS << self._self_heal_attempts
            if delay_ms > _SELF_HEAL_BACKOFF_CAP_MS:
                delay_ms = _SELF_HEAL_BACKOFF_CAP_MS
            self._self_heal_attempts += 1
        self._self_heal_retry_at_ticks = self._deadline(delay_ms, now_ms=now_ms)

    def _attempt_self_heal(self, now_ms):
        """Reset transient state, build a fresh connector, enter AWAITING_TRANSPORT.

        Best-effort: if ``transport_factory()`` itself raises (typically
        because wifi is still down) the client stays in ``FAILED`` and
        the next handle tick retries.  The actual DNS / TCP / TLS work
        happens across subsequent ticks in :meth:`_advance_connector`,
        bounded by the transport-attempt deadline armed here, so this
        method does not block.

        Returns ``True`` when self-heal succeeded and the client is in
        ``AWAITING_TRANSPORT``.  Returns ``False`` when building the
        connector failed and the client is still ``FAILED``.
        """
        # Close the dead socket best-effort so we don't leak file descriptors
        # on long-running boards.
        try:
            if self._socket is not None:
                self._socket.close()
        except OSError:  # pragma: no cover - defensive
            pass
        self._socket = None
        # Reset transient state for the fresh connection.  Keep the
        # in-flight QoS 1 table intact when clean_session=False so a
        # broker that supports session resumption can pick up where we
        # left off.  Clear it on clean_session=True (the safer default).
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
        """Fault a transport attempt that outlived its overall window.

        Connectors never time out on their own (their ``next_deadline``
        is ``None`` by design — the consumer owns the deadline), so a
        black-holed TCP connect or stalled TLS handshake would park
        forever without this.  Returns ``True`` when it fired: the
        connector is cancelled, ``last_error`` names the dead phase,
        and the client is ``FAILED`` for the next tick's self-heal.
        """
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
        """Tick the connector one phase; promote socket when ``ready``.

        Returns ``True`` when the connector reached ``ready`` this
        tick — in which case the socket is promoted to ``self._socket``,
        the CONNECT packet is enqueued, and ``state`` is now
        ``CONNECTING`` (the caller falls through to drain CONNECT).

        Returns ``False`` when the connector is still in flight (state
        unchanged) or has failed (state is now ``FAILED``).
        """
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
        """Return the next free QoS-1 packet-id in the 1-65535 cycle.

        Wraps at 65535 back to 1 (id 0 is reserved by the spec).  Raises
        :class:`OverflowError` when every id is already in flight rather
        than silently reusing one.
        """
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
        """Send one queue packet this tick, plus any owed PUBACK batch.

        One user/protocol packet ``send`` per tick keeps the tick short
        so other runner-registered services (LED, buttons, LCD) get CPU
        time between MQTT sends.  A coalesced PUBACK batch at the head
        of the queue (queued by ``_read_inbound``; the only outbound
        bytes whose first byte is the PUBACK type) is flushed WITHOUT
        consuming that budget: the acks a tick's reads incurred leave
        in the same tick, so the ack rate tracks the inbound dispatch
        rate and a sustained QoS-1 stream can't starve keepalive
        PINGREQs or user publishes out of the send slot.  At most two
        sends per tick — the batch, then one packet.  QoS-0 callback
        markers are not I/O and fire immediately as they reach the
        head of the queue.

        Each item is either ``bytes`` (a packet, possibly several
        PUBACKs concatenated) or a
        ``("__qos0_callback__", callback, topic, payload)`` tuple
        (a deferred QoS 0 on_publish hook).
        """
        # Resume a previous partial send first.  Wire-ordering invariant:
        # the remainder of a partial packet lands before any new packet
        # this client appends, so this branch returns immediately after
        # one send attempt regardless of outcome.
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
            # Drain leading QoS 0 callback markers (no I/O) up to the
            # next real packet.  These fire on dequeue and don't consume
            # the per-tick send budget.
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
                # Cache a memoryview so the resume path slices ``view[offset:]``
                # zero-copy instead of copying the unsent tail each tick (the
                # WS-2 cached-view shape).  packet is immutable ``bytes``, so
                # the view is safe to hold across ticks.
                self._partial_send = (memoryview(packet), sent)
                self._tx_queue.popleft()
                if is_puback_batch:
                    # The unsent tail still owes acks; ``_partial_send``
                    # keeps the recv suppressed until it lands.
                    self._puback_batch_queued = False
                self._update_send_deadline(sent)
                return
            self._tx_queue.popleft()
            self._update_send_deadline(sent)
            if is_puback_batch:
                self._puback_batch_queued = False
                continue  # Ack flush done; the packet budget is unspent.
            # Drain trailing QoS 0 callback markers so the on_publish
            # hook for the just-sent QoS 0 PUBLISH fires this tick
            # instead of waiting for the next one.  Wire-ordering
            # invariant intact: markers carry no I/O.
            self._drain_callback_markers()
            return

    def _update_send_deadline(self, bytes_sent):
        """Maintain ``_send_deadline_ticks`` after a drain step.

        Invariants:
        - Queue empty AND no partial send pending: deadline cleared.
        - Otherwise some bytes still want to go out: arm the deadline.
          If progress was made this step (``bytes_sent > 0``), re-arm
          so a steady drip of sends doesn't false-fail.  If no progress
          AND no deadline is armed yet, arm now so the timeout starts
          counting down.  If no progress AND a deadline is already
          armed, leave it alone -- it's the running timer that the
          ``_check_deadlines`` step inspects.
        """
        if not self._tx_queue and self._partial_send is None:
            self._send_deadline_ticks = None
            return
        if bytes_sent > 0 or self._send_deadline_ticks is None:
            self._send_deadline_ticks = self._deadline(self._send_timeout_ms)

    def _drain_callback_markers(self):
        """Pop QoS 0 callback markers off the head of the tx queue, firing each.

        Returns once the head is no longer a marker (or queue is empty).
        Markers carry no I/O so this doesn't consume the per-tick send
        budget.
        """
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
        """Send *payload*.  Returns bytes sent (may be 0 on EAGAIN)."""
        try:
            return self._socket.send(payload)
        except OSError as error:
            if error.errno == errno.EAGAIN:  # pragma: no cover - EAGAIN handling
                return 0
            raise

    def _enqueue_user_tx(self, *items):
        """Append one or more user-initiated items as a unit, honoring the cap.

        Raises :class:`MQTTBackpressureError` when the queue lacks room
        for every item, signaling the caller to drain via :meth:`handle`
        and retry.  Multiple items (a QoS-0 packet plus its callback
        marker) are checked together and enqueued atomically: the call
        lands all of them or none, so a callback-bearing publish can't
        half-land its packet without its marker, and can't slip the cap
        one item at a time.  Each item occupies a slot and pins its own
        payload reference, so the cap counts every item, not every
        logical publish.

        Internal protocol packets (PUBACK responses, deadline-triggered
        retransmits, PINGREQ) bypass this cap because failing to enqueue
        them would break QoS-1 / keepalive guarantees.  The cap exists
        to catch a runaway publisher, not to block protocol bookkeeping.
        """
        if len(self._tx_queue) + len(items) > self._max_tx_queue_size:
            raise MQTTBackpressureError(
                f"tx queue full ({len(self._tx_queue)} + {len(items)} > "
                f"{self._max_tx_queue_size}); call handle() to drain "
                "and retry",
            )
        for item in items:
            self._tx_queue.append(item)

    def _enqueue_internal_tx(self, packet, *, front=False):
        """Queue a protocol packet (PUBACK, retransmit, PINGREQ) into the
        headroom above the user cap.

        Returns ``True`` when queued.  The structural bound is checked
        here rather than left to the deque's overflow, which raises
        ``IndexError`` on MicroPython / CircuitPython and silently evicts
        the opposite end (a queued user packet) on CPython.  At the cap
        the packet is NOT queued and the caller decides: retransmit and
        PINGREQ skip-and-retry next tick (both recoverable), while the
        PUBACK flush in ``_read_inbound`` escalates ``False`` to a
        FAILED fault rather than losing a protocol packet.  *front*
        queues ahead of pending user packets (a PUBACK the broker is
        waiting on).
        """
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
        """Whether this tick's recv is skipped for outbound backpressure.

        True while a coalesced PUBACK batch is still queued unsent, or
        a partial send is pending — both mean the socket isn't taking
        our bytes as fast as the broker is producing theirs.  Reading
        on regardless would grow the ack backlog without bound; leaving
        the bytes unread in the kernel buffer instead closes the TCP
        receive window, so the broker throttles at its end and OUR
        memory stays bounded.  Deadline checks run before the read in
        ``handle``, so suppression never defers fault detection, and
        the send timeout bounds how long a wedged socket can hold the
        suppression.
        """
        return self._puback_batch_queued or self._partial_send is not None

    def _read_inbound(self, now_ms):
        """Pull at most one chunk off the socket and dispatch buffered packets.

        Skipped entirely while :meth:`_recv_suppressed` — the previous
        tick's PUBACK batch hasn't reached the wire yet, so inbound
        dispatch pauses rather than piling up acks (which also keeps
        cross-tick PUBACKs in receipt order: a second batch can never
        queue in front of an unsent first).

        ONE ``recv_into`` per tick (the syscall is the expensive part
        and the one that needs to yield back to the runner); ALL
        complete packets already in the decoder buffer dispatch in
        the same call (parsing is CPU-bound and allocation-light, and
        without a wake event the next tick may not fire until the
        keepalive 30 s away, so leaving buffered packets undispatched
        would stall inbound delivery).  The recv is capped at
        ``recv_budget_per_tick``, which thereby also bounds how many
        packets one tick can dispatch and how large a PUBACK batch it
        can owe.
        """
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
                    # Non-blocking ``recv_into`` returning 0 is a clean
                    # peer FIN; the no-data path raises ``OSError(EAGAIN)``
                    # and is handled above.  Raise so ``handle()`` transitions
                    # to FAILED and the next tick can self-heal.
                    raise MQTTProtocolError("broker closed connection")
                self._decoder.advance(got)

        # Collect PUBACKs for this tick's inbound QoS-1 publishes and
        # flush them once after dispatch as a single coalesced batch,
        # so they reach the wire in receipt order (MQTT-4.6.0-2).
        # Reuse the instance list (cleared here)
        # instead of a fresh literal every tick; an early return below
        # (disconnect mid-dispatch) leaves items for the next tick's
        # clear to drop, matching the pre-reuse drop-on-return behavior.
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
            # An inbound callback (on_message, a PUBACK callback) may have
            # called disconnect(); it clears the tx queue and leaves
            # CONNECTED, so stop dispatching and don't re-queue anything.
            if self.state != ProtocolState.CONNECTED:
                return
        # Coalesce the tick's PUBACKs (already in receipt order) into
        # ONE front-of-queue entry: the drain flushes it in a single
        # send that doesn't consume the tick's packet budget, so the
        # ack rate tracks the dispatch rate instead of falling behind
        # it at one PUBACK per tick.  A queue already at the hard cap
        # still faults instead of dropping — a lost PUBACK (or a packet
        # evicted to make room for one) silently corrupts the wire
        # stream, while a FAILED transition lets self-heal rebuild
        # cleanly and the broker redeliver whatever was never acked.
        # With batching + recv suppression that backstop is only
        # reachable when retransmits or replays have already consumed
        # the whole protocol headroom.
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
        # Drop the just-enqueued references promptly; the next tick's
        # clear covers the early-return path.
        pending_pubacks.clear()

    def _handle_inbound_publish(self, packet, pending_pubacks):
        """Fire on_message + (for QoS 1) collect a PUBACK to send."""
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
        """Apply the configured WhenOversized policy."""
        if self._when_oversized == WhenOversized.DROP_SILENT:
            pass  # Drop without notification.
        elif self._when_oversized == WhenOversized.DROP_WITH_EVENT:
            self.on_oversized(packet.reported_length, packet.topic)
        elif self._when_oversized == WhenOversized.DISCONNECT:
            raise MQTTProtocolError(
                f"oversized message on topic {packet.topic!r} "
                f"({packet.reported_length} bytes)",
            )
        # PUBACK a QoS-1 oversize even when dropping the payload, so the
        # broker doesn't retransmit — but only when the packet_id
        # survived: an oversize *topic prelude* yields packet_id=None,
        # which encode_puback cannot pack (struct.error), so skip the
        # ack and let the broker redeliver rather than crashing.
        if (
            packet.qos == 1
            and packet.packet_id is not None
            and self._when_oversized != WhenOversized.DISCONNECT
        ):
            pending_pubacks.append(encode_puback(packet_id=packet.packet_id))

    def _handle_ack(self, packet, now_ms):
        """Match an inbound ack to its pending entry.  PINGRESP is tolerated.

        An unmatched PUBACK / SUBACK / UNSUBACK faults to FAILED because
        a broker that ACKs a packet_id we never issued is a real bug.
        PINGRESP is racy in keepalive-timeout / self-heal corners
        and silently ignored.
        """
        if packet.packet_type == PACKET_CONNACK:
            self._handle_connack(packet, now_ms)
            return
        if packet.packet_type == PACKET_PINGRESP:
            self._discard_pending(_AWAIT_PINGRESP, packet_id=None)
            return
        if packet.packet_type == PACKET_PUBACK:
            in_flight = self._in_flight.pop(packet.packet_id, None)
            if in_flight is None:
                # No pending entry: the common cause is a duplicate
                # PUBACK — the broker acking both our original publish
                # and the DUP retransmit the retry path sent after a
                # slow (not lost) first ack.  Tolerate it like PINGRESP
                # rather than tearing down the session the retry exists
                # to protect.
                return
            if in_flight.callback is not None:
                in_flight.callback()
            return
        if packet.packet_type == PACKET_SUBACK:
            # MQTT 3.1.1 §3.9.3: a granted_qos byte of 0x80 (== 128)
            # signals "Failure", meaning the broker rejected the
            # subscription (ACL deny, topic-not-permitted, etc.).
            # Surface as a protocol error so the application sees the
            # failure instead of silently inheriting a never-matched
            # subscription.
            if packet.granted_qos and 0x80 in packet.granted_qos:
                # Evict the rejected filter from _subscriptions before
                # faulting, so the self-heal reconnect's replay doesn't
                # re-issue it and re-earn the same rejection forever.
                self._evict_rejected_subscription(packet.packet_id)
                raise MQTTProtocolError(
                    f"SUBACK rejection (packet_id {packet.packet_id}, "
                    f"granted_qos {packet.granted_qos}) — broker refused "
                    "one or more subscription filters"
                )
            matched = self._discard_pending(
                _AWAIT_SUBACK, packet_id=packet.packet_id,
            )
            if matched is None:
                raise MQTTProtocolError(
                    f"SUBACK for unknown packet_id {packet.packet_id}",
                )
            # The SUBACK carries only the id; the matched pending entry
            # supplies the topic, which keys the desired-set entry whose
            # second slot holds the one-shot on_subscribe.  Fire and clear
            # it on the FIRST grant (direct send or replay); a no-op when
            # the topic was unsubscribed meanwhile or the one-shot already
            # fired, so self-heal replays stay callback-silent.
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
        """CONNACK return-code 0 = success, anything else = failure."""
        self._discard_pending(_AWAIT_CONNACK, packet_id=None)
        if packet.return_code != 0:
            # Codes 1-5 are the rejection codes a broker may send
            # (MQTT 3.1.1 §3.2.2.3).  Built inline so the dict only
            # allocates on rejection (rare).  The success path never
            # touches it.
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
            # Codes 1/2/4/5 can't be fixed by reconnecting with the same
            # CONNECT packet, so latch permanent-failure and stop
            # self-healing.  Code 3 (server unavailable) stays transient.
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
        # Session honesty: with clean_session=False a broker may resume
        # our prior session.  When it confirms it did
        # (session-present=1), our subscriptions still live at the broker,
        # so replaying them is wasted traffic — skip it.  With
        # clean_session=True the broker always forgets, and with
        # session-present=0 it did not resume, so replay to restore the
        # inbound stream.  The QoS-1 in-flight table is already preserved
        # across a clean_session=False reconnect (_attempt_self_heal), so
        # gating replay here completes the resume rather than half-wiring
        # it.
        if self._clean_session or not packet.session_present:
            self._replay_subscriptions()
        # Flush publishes buffered before this CONNACK, oldest first and
        # ahead of any publish the on_connect callback issues.
        self._drain_pre_connect_queue()
        self.on_connect()

    def _replay_subscriptions(self):
        """Re-issue SUBSCRIBE for every entry in the desired subscription set.

        Runs as the last step of every successful CONNACK (gated by the
        session-present check in :meth:`_handle_connack`).  This one
        path serves two jobs: it puts a pre-connect *declaration* on the
        wire for the first time, and on a self-heal-driven reconnect it
        restores the inbound stream the broker forgot (clean_session=True).

        The replay fires the per-topic ``on_subscribe`` only through the
        one-shot stored in each entry's second slot (the SUBACK branch of
        :meth:`_handle_ack` fires and clears it): a pre-connect
        declaration's first SUBACK arrives via this replay and fires its
        callback once, while an already-fired subscription (a prior direct
        send or an earlier replay) has a cleared one-shot and stays silent
        — so a self-heal reconnect does not re-notify per topic.
        """
        if not self._subscriptions:
            return
        for topic, entry in self._subscriptions.items():
            qos = entry[0]
            packet_id = self._allocate_packet_id()
            packet = encode_subscribe(
                packet_id=packet_id, subscriptions=[(topic, qos)],
            )
            # Replay is protocol bookkeeping, not a user publish: route
            # it through the headroom instead of the user cap.  Going
            # through _enqueue_user_tx would raise MQTTBackpressureError
            # once the stored subscription count exceeds the cap, which
            # handle() turns into FAILED -> reconnect -> replay again,
            # an unbreakable loop that never reconnects.
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
        """Drop the topic filter tied to a rejected SUBACK from _subscriptions.

        Looks up the pending SUBACK entry for *packet_id* to recover the
        topic (a SUBACK carries only the id, not the filter) and removes
        it so it is never replayed on reconnect.  A no-op when the entry
        or its topic is absent.
        """
        for pending in self._pending_responses:
            if pending.awaiting == _AWAIT_SUBACK and pending.packet_id == packet_id:
                if pending.topic is not None:
                    self._subscriptions.pop(pending.topic, None)
                return

    def _discard_pending(self, awaiting, *, packet_id, callback_arg=None):
        """Find and remove the matching :class:`PendingResponse`, then fire its callback.

        Returns the removed :class:`PendingResponse` when a match was
        found (a truthy object, so ``if not matched`` / ``if matched is
        None`` both read cleanly), letting the SUBACK caller recover the
        entry's ``topic``.  Returns ``None`` when no matching pending
        entry exists (caller decides whether that's a protocol fault or
        a tolerated late arrival).
        """
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
        """Retry / fault on expired in-flight + pending entries.

        Neither loop allocates a copy of its source collection: the
        in-flight retry path mutates only entry attributes (dict
        identity preserved), and both the in-flight retry-max path
        and the pending-response expiry path mutate then ``return``
        immediately, so the iterator never sees the modified state.
        Steady-state zero allocation when nothing is expired.
        """
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
            # The DUP-flagged retransmit (bit 3 of byte 0, MQTT 3.1.1
            # §4.3.2) is identical every retry, so build it once and reuse
            # it instead of re-copying packet_bytes on each expiry.
            if entry.dup_packet_bytes is None:
                dup_packet = bytearray(entry.packet_bytes)
                dup_packet[0] |= 0x08
                entry.dup_packet_bytes = bytes(dup_packet)
            # Bounded enqueue: many overdue in-flight publishes in one
            # tick can exceed the headroom.  When it's full, leave this
            # entry's deadline as-is so it retries next tick without
            # burning a retry attempt, rather than evicting a queued
            # packet or crashing.
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

        # Send timeout: the socket has been non-writable with a packet
        # queued for longer than the configured limit.  Fires only when
        # the deadline is armed (queue non-empty or partial-send pending)
        # AND a previous drain failed to make progress for ``send_timeout_ms``.
        if self._send_deadline_ticks is not None:
            if self._ticks.ticks_diff(self._send_deadline_ticks, now_ms) <= 0:
                self.last_error = MQTTError(
                    "send timeout: tx queue made no progress for "
                    f"{self._send_timeout_ms} ms",
                )
                self.state = ProtocolState.FAILED
                return

    def _check_keepalive(self, now_ms):
        """Send a PINGREQ when half the keepalive interval has elapsed."""
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
        """Return a tick value *offset_ms* in the future.

        Pass *now_ms* when computing a deadline inside the tick loop so
        every deadline armed during that tick shares one ``ticks_ms()``
        reading.  Omit *now_ms* from user-entry paths that run outside
        the tick loop, where a fresh ``ticks_ms()`` is captured.
        """
        if now_ms is None:
            now_ms = self._ticks.ticks_ms()
        return self._ticks.ticks_add(now_ms, offset_ms)
