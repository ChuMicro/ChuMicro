"""MQTT 3.1.1 client built on chumicro-sockets + chumicro-timing.

:class:`MQTTClient` is the entry point.  Runner-shaped —
:meth:`check(now_ms) -> bool` reports whether work is pending;
:meth:`handle(now_ms)` performs one tick of progress.  No threads,
no async — cooperative dispatch in the caller's tick loop.

The connection model lives here too (:class:`ProtocolState`,
:class:`Awaiting`, :class:`InFlightTable`, :class:`PendingResponse`,
:class:`InFlightPublish`) so the device-side bundle is two files
(plus ``__init__``) instead of seven; the wire-format primitives
sit in :mod:`chumicro_mqtt._wire`.
"""

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
    _topic_levels_match,
    encode_connect,
    encode_puback,
    encode_publish,
    encode_subscribe,
    encode_unsubscribe,
)


def _is_eagain(error):
    return getattr(error, "errno", None) in (11, 35)


# ---------------------------------------------------------------------------
# Connection state + pending-work tracking
# ---------------------------------------------------------------------------


class ProtocolState:
    """Connection lifecycle states.

    Transitions monotonically forward except after a fault::

      DISCONNECTED -> CONNECTING -> CONNECTED -> DISCONNECTED
                                              \\-> FAILED   -> DISCONNECTED

    ``disconnect()`` is synchronous (DISCONNECT packet + close), so there
    is no intermediate "disconnecting" state to observe.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"


class Awaiting:
    """Tags identifying which broker response a pending work-item expects."""

    CONNACK = "connack"
    PINGRESP = "pingresp"
    PUBACK = "puback"
    SUBACK = "suback"
    UNSUBACK = "unsuback"


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


class InFlightTable:
    """Indexed collection of :class:`InFlightPublish`, keyed by packet_id.

    Centralizes packet-id allocation: callers ask for the next free
    id, the table picks the next 1-65535 wraparound that isn't already
    in flight.  Packet-id 0 is reserved by the spec.  An exhausted
    id-space (every 65535 ids in flight) raises :class:`OverflowError`
    rather than silently reusing.
    """

    def __init__(self):
        self._entries = {}
        self._next_id = 1

    def __len__(self):
        return len(self._entries)

    def __contains__(self, packet_id):
        return packet_id in self._entries

    def __iter__(self):
        return iter(self._entries.values())

    def allocate_id(self):
        """Return the next free packet-id (1-65535)."""
        for _attempt in range(65535):
            candidate = self._next_id
            self._next_id += 1
            if self._next_id > 65535:
                self._next_id = 1
            if candidate not in self._entries:
                return candidate
        raise OverflowError(
            "MQTT in-flight table is full (65535 packet-ids in use)",
        )

    def add(self, entry):
        """Insert *entry*; raises :class:`KeyError` on packet_id collision."""
        if entry.packet_id in self._entries:
            raise KeyError(f"packet_id {entry.packet_id} already in flight")
        self._entries[entry.packet_id] = entry

    def get(self, packet_id):
        """Return the in-flight entry for *packet_id* or ``None``."""
        return self._entries.get(packet_id)

    def discard(self, packet_id):
        """Remove and return the in-flight entry for *packet_id*, or ``None``."""
        return self._entries.pop(packet_id, None)


class PendingResponse:
    """A non-publish response (CONNACK / SUBACK / UNSUBACK / PINGRESP) we're waiting for.

    Each carries an :class:`Awaiting` tag, a deadline, an optional
    packet_id, and an optional callback that fires once on receipt.
    Multiple pending responses can coexist — tracking is per-entry
    rather than via a single broad waiting-state lock.
    """

    def __init__(self, awaiting, deadline_ticks, packet_id=None, callback=None):
        self.awaiting = awaiting
        self.deadline_ticks = deadline_ticks
        self.packet_id = packet_id
        self.callback = callback


# ---------------------------------------------------------------------------
# WhenOversized policy
# ---------------------------------------------------------------------------


class WhenOversized:
    """Policy for inbound PUBLISH whose payload exceeds ``max_message_bytes``."""

    #: Drop silently; PUBACK the broker.
    DROP_SILENT = "drop_silent"

    #: Default.  Drop the payload, fire ``on_oversized(reported_length, topic)``,
    #: still PUBACK so the broker doesn't retransmit.
    DROP_WITH_EVENT = "drop_with_event"

    #: Treat as a protocol error: disconnect.  Use when application
    #: invariants assume payloads fit within the configured cap.
    DISCONNECT = "disconnect"


def _no_callback(*_args, **_kwargs):
    """Default no-op callback so handlers can be stored unconditionally."""
    return None


# ---------------------------------------------------------------------------
# MQTTPublisher — topic-binder convenience helper
# ---------------------------------------------------------------------------


class MQTTPublisher:
    """A topic-, qos-, retain-bound publisher.

    Construct via :meth:`MQTTClient.publisher` rather than directly —
    the factory carries the right client reference and respects the
    client's ``root_topic`` resolution.

    Usage::

        publisher = client.publisher("temperature", qos=1, retain=False)
        publisher.publish(b"23.4")        # bytes
        publisher.publish("23.4")          # str auto-encoded
        publisher.publish(b"23.4", on_publish=callback)

    The bound topic resolves through the client's ``root_topic`` /
    ``client_id`` prefixing scheme if configured.  For unprefixed
    publishing, use :meth:`MQTTClient.publish_raw` directly.
    """

    def __init__(self, client, topic, *, qos=0, retain=False):
        self._client = client
        self._topic = topic
        self._qos = qos
        self._retain = retain

    def publish(self, payload, *, on_publish=None):
        """Publish *payload* under the bound topic / qos / retain.

        Delegates to :meth:`MQTTClient.publish` — auto-encoding str
        payload, prefixing via ``root_topic``, allocating a packet_id
        for QoS 1.
        """
        self._client.publish(
            self._topic, payload,
            qos=self._qos, retain=self._retain,
            on_publish=on_publish,
        )


def _new_tx_queue(maxlen):
    """Return a fresh outbound ``deque`` sized at *maxlen* with ``appendleft``.

    MicroPython and CircuitPython require ``flags=1`` as a third
    positional argument to enable ``appendleft`` (and other
    bidirectional ops); CPython rejects the third arg with
    ``TypeError`` because its full-featured deque needs no flag.  Try
    the MP/CP shape first so embedded gets the cheaper path; fall back
    to the 2-arg shape on CPython.

    """
    try:
        return deque((), maxlen, 1)
    except TypeError:  # CPython: 2-arg constructor, appendleft already supported.
        return deque((), maxlen)


def _force_non_blocking(socket):
    """Best-effort ``setblocking(False)``.  The tick-based RX path requires
    non-blocking recv; MP plain TCP defaults to blocking.  Some MP TLS
    adapters lack ``setblocking`` entirely — the ``getattr`` + ``try``
    handles both shapes."""
    setblocking = getattr(socket, "setblocking", None)
    if setblocking is None:
        return
    try:
        setblocking(False)
    except (OSError, AttributeError):  # pragma: no cover — defensive
        pass


# ---------------------------------------------------------------------------
# MQTTClient
# ---------------------------------------------------------------------------


class MQTTClient:
    """Non-blocking MQTT 3.1.1 client (QoS 0 + 1).

    Construct with an already-connected :class:`TCPClientSocket` and
    user knobs; then drive via :meth:`check` / :meth:`handle` from a
    runner tick or a hand-rolled loop.  All callbacks fire from
    :meth:`handle` — never from a thread or interrupt.

    For config-driven construction, see :meth:`from_config` —
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
        socket_factory: object | None = None,
    ) -> "MQTTClient":
        """Build an :class:`MQTTClient` from runtime config.

        Reads ``mqtt.broker.host`` / ``mqtt.broker.port`` (required when
        no *socket* / *socket_factory* override), plus optional
        ``mqtt.client_id`` / ``mqtt.keep_alive_seconds`` / ``mqtt.username``
        / ``mqtt.password``.  A *socket* or *socket_factory* override
        bypasses the auto-built factory entirely.  Missing broker keys
        raise :class:`chumicro_config.MissingConfigKey`.
        """
        if socket is None and socket_factory is None:
            # Lazy import so users who pass their own socket / socket_factory
            # don't pull chumicro_sockets into the deploy graph.  See
            # ``chumicro_mqtt.sockets_factory`` for the helper itself.
            try:
                from chumicro_mqtt.sockets_factory import (  # noqa: PLC0415 - lazy
                    chumicro_sockets_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_mqtt.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or "
                    "not on the board) — pass socket_factory= or "
                    "socket= explicitly.",
                ) from exception

            socket_factory = chumicro_sockets_factory(
                config, radio=radio, ssl_context=ssl_context,
            )
        return cls(
            socket=socket,
            socket_factory=socket_factory,
            client_id=config.get("mqtt.client_id", "chumicro-mqtt"),
            keep_alive_seconds=config.get("mqtt.keep_alive_seconds", 60),
            username=config.get("mqtt.username"),
            password=config.get("mqtt.password"),
        )

    def __init__(
        self,
        socket: object | None = None,
        *,
        socket_factory: object | None = None,
        client_id: str,
        root_topic: str | None = None,
        keep_alive_seconds: int = 60,
        ack_timeout_seconds: float = 5.0,
        publish_retry_max: int = 3,
        username: str | None = None,
        password: str | None = None,
        clean_session: bool = True,
        will_topic: str | None = None,
        will_topic_raw: str | None = None,
        will_message: bytes | None = None,
        will_qos: int = 0,
        will_retain: bool = False,
        rx_buffer_size: int | None = None,
        max_message_bytes: int | None = None,
        when_oversized: WhenOversized = WhenOversized.DROP_WITH_EVENT,
        recv_budget_per_tick: int = 1024,
        max_tx_queue_size: int = 20,
        ticks: object | None = None,
    ) -> None:
        """Wire up the client.

        Args:
            socket: An already-connected, non-blocking object exposing
                ``recv_into`` / ``send`` / ``close`` / ``setblocking``
                — see the user guide's "Bring your own transport" table
                for the per-method contract.  The client takes
                ownership; :meth:`disconnect` closes it.  May be
                ``None`` when *socket_factory* is provided — the
                factory fires on :meth:`connect` and self-heal, never
                from ``__init__``.
            socket_factory: Optional zero-arg callable returning an
                object of the same shape as *socket*.  Used in two
                paths: (1) when *socket* is ``None``, :meth:`connect`
                invokes the factory to build the initial transport;
                (2) when the client transitions to ``FAILED`` after a
                wifi-drop / socket-death, the next ``handle()`` rebuilds
                the socket and re-issues ``connect()`` automatically.
                Without a factory, the caller must supply *socket* and
                manage reconnect themselves.  Construction is always
                side-effect free — the factory only fires from
                ``connect()`` / self-heal, never from ``__init__``.
            client_id: MQTT client identifier — must be unique per broker.
                Doubles as the per-device segment in the topic-prefix
                scheme when *root_topic* is set.
            root_topic: Optional prefix applied automatically by
                :meth:`publish` / :meth:`subscribe` / :meth:`unsubscribe`.
                When set, every prefixed topic becomes
                ``<root_topic>/<client_id>/<topic>``.  ``None`` (default)
                disables prefixing — topics go on the wire as written.
                Use :meth:`publish_raw` / :meth:`subscribe_raw` /
                :meth:`unsubscribe_raw` to bypass prefixing on individual
                calls (system topics, bridge topics, etc.).
            keep_alive_seconds: Broker idle timeout.  PINGREQ runs at
                half this interval client-side.
            ack_timeout_seconds: Per-PUBACK / SUBACK / etc. deadline.
                Triggers a retry (PUBLISH) or fault (everything else).
            publish_retry_max: Max QoS 1 PUBLISH retries before giving
                up + transitioning to FAILED.
            username: Optional auth username (paired with *password*).
            password: Optional auth password.
            clean_session: ``False`` resumes persistent broker session
                state for QoS 1+ retransmit-across-reconnects.
            will_topic: Topic for the broker's last-will message —
                published on uncleanly-dropped connection.  Resolves
                through the ``root_topic`` / ``client_id`` prefix
                scheme if set.  ``None`` disables the will.  Mutually
                exclusive with *will_topic_raw*.
            will_topic_raw: Last-will topic without prefix resolution.
                Use when the will needs to land outside the per-device
                topic hierarchy (system topics, bridges).  Mutually
                exclusive with *will_topic*.
            will_message: Payload for the broker's last-will message.
            will_qos: QoS for the will message (0 or 1).
            will_retain: ``True`` retains the will on the broker.
            rx_buffer_size: Steady-state RX buffer size (default 256).
                Inbound PUBLISHes ≤ this size parse inline with no
                allocation.  Larger messages route through the tier-2
                intact-delivery or tier-3 oversized paths — see
                ``max_message_bytes``.
            max_message_bytes: Cap on a single inbound PUBLISH for
                intact delivery (default 8 KB).  Messages at or below
                this size are delivered to :attr:`on_message` with
                their full payload (one-shot allocation, freed after
                delivery).  Above this size the configured
                :class:`WhenOversized` policy applies — the payload is
                discarded without a payload-sized heap allocation.
            when_oversized: Policy for inbound messages above
                ``max_message_bytes``.  See :class:`WhenOversized`.
            recv_budget_per_tick: Soft cap on bytes drained from the
                socket in a single :meth:`handle` call (default 1024).
                Bounds tick latency when a large inbound PUBLISH is
                mid-flight so concurrent runner tasks keep getting
                CPU time.
            max_tx_queue_size: Maximum number of pending outbound
                packets (default 20).  Appending past the cap raises
                :class:`MQTTBackpressureError`; raise the cap for
                bursty publishers.
            ticks: Optional tick source — any object exposing
                ``ticks_ms``, ``ticks_diff``, ``ticks_add`` (matches
                the ``chumicro_timing.ticks`` submodule shape).
                Defaults to that submodule (real clock); tests pass
                ``FakeTicks`` from ``chumicro_timing.testing``.
        """
        if socket is None and socket_factory is None:
            raise ValueError(
                "MQTTClient requires either a connected socket or a "
                "socket_factory (or both — factory is used for self-heal "
                "after wifi-drop)."
            )
        if will_topic is not None and will_topic_raw is not None:
            raise ValueError(
                "will_topic (prefixed) and will_topic_raw (verbatim) are "
                "mutually exclusive — pass at most one."
            )
        self._socket = socket
        self._socket_factory = socket_factory
        if self._socket is not None:
            # MP plain TCP defaults to blocking; the tick-based recv
            # path requires EAGAIN-on-no-data or it stalls the loop.
            _force_non_blocking(self._socket)
        self._user_wants_connected = False
        self._client_id = client_id
        self._root_topic = root_topic
        self._keep_alive_seconds = keep_alive_seconds
        self._ack_timeout_ms = int(ack_timeout_seconds * 1000)
        self._publish_retry_max = publish_retry_max
        self._username = username
        self._password = password
        self._clean_session = clean_session
        # Resolve the will topic once at construction.  ``will_topic``
        # gets the root_topic/client_id prefix; ``will_topic_raw`` goes
        # verbatim.  CONNECT later uses ``self._will_topic`` directly.
        if will_topic_raw is not None:
            self._will_topic = will_topic_raw
        elif will_topic is not None:
            self._will_topic = self._prefixed_topic(will_topic)
        else:
            self._will_topic = None
        self._will_message = will_message
        self._will_qos = will_qos
        self._will_retain = will_retain
        self._when_oversized = when_oversized
        self._recv_budget_per_tick = recv_budget_per_tick
        self._max_tx_queue_size = max_tx_queue_size

        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        self._ticks = ticks

        decoder_kwargs = {}
        if rx_buffer_size is not None:
            decoder_kwargs["rx_buffer_size"] = rx_buffer_size
        if max_message_bytes is not None:
            decoder_kwargs["max_message_bytes"] = max_message_bytes
        self._decoder_kwargs = decoder_kwargs
        self._decoder = PacketDecoder(**decoder_kwargs)

        self.state = ProtocolState.DISCONNECTED
        self._in_flight = InFlightTable()
        self._pending_responses = []
        # 64-slot headroom above the user cap so the QoS-1 retry path
        # and PINGREQ — neither of which checks for overrun — can't
        # silently lose protocol packets when the queue is at the user
        # cap.  ``_enqueue_user_tx`` enforces the cap; everything else
        # goes through ``append`` / ``appendleft`` directly.
        self._tx_queue = _new_tx_queue(max_tx_queue_size + 64)
        self._partial_send = None  # (bytes, offset) when last send was short.

        self._next_ping_due_ticks = 0
        self._ping_interval_ms = max(1000, keep_alive_seconds * 1000 // 2)

        # Callbacks default to no-ops so handlers can call without branching.
        self.on_message = _no_callback
        self.on_connect = _no_callback
        self.on_disconnect = _no_callback
        self.on_subscribe = _no_callback
        self.on_unsubscribe = _no_callback
        self.on_publish = _no_callback
        self.on_oversized = _no_callback
        self._pattern_handlers = []
        self.last_error = None

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def connect(self):
        """Open the TCP socket (if needed) and queue a CONNECT packet.

        When the client was constructed with only a ``socket_factory``,
        the factory is invoked here — this is the first network I/O
        the client does.  When the factory raises, the client
        transitions to ``FAILED`` (``last_error`` carries the underlying
        ``OSError``) instead of letting the exception propagate; the
        runner contract is to introspect ``state`` / ``last_error``,
        not to wrap every ``connect()`` call in a try.

        After the socket is in hand, the MQTT CONNECT packet is queued
        and the state transitions to ``CONNECTING``.  The actual MQTT
        handshake completes on subsequent :meth:`handle` ticks.  Callers
        loop ``while client.state in {DISCONNECTED, CONNECTING}: handle()``
        or run under a Runner.

        Raises:
            MQTTError: Called in a non-DISCONNECTED state.
        """
        if self.state != ProtocolState.DISCONNECTED:
            raise MQTTError(
                f"connect() requires DISCONNECTED state, was {self.state}",
            )
        if self._socket is None:
            # No pre-built socket — invoke the factory.  Factory errors
            # land as ``FAILED`` + ``last_error`` rather than propagating
            # so the runner contract holds; a follow-up tick (or the
            # caller's reconnect strategy) can retry via self-heal.
            try:
                new_socket = self._socket_factory()
            except OSError as factory_error:
                self.last_error = MQTTError(
                    f"socket factory failed: {factory_error}",
                )
                self.state = ProtocolState.FAILED
                self._user_wants_connected = True
                return
            self._socket = new_socket
            _force_non_blocking(self._socket)
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
                awaiting=Awaiting.CONNACK,
                deadline_ticks=self._deadline(self._ack_timeout_ms),
            ),
        )
        self.state = ProtocolState.CONNECTING
        self._user_wants_connected = True

    def disconnect(self):
        """Queue a DISCONNECT packet, close the socket, mark DISCONNECTED.

        Best-effort: any exception during send/close is swallowed so
        the client always returns in a known DISCONNECTED state.
        """
        try:
            self._send_raw(PACKET_DISCONNECT)
        except Exception:  # noqa: BLE001 — disconnect is best-effort  # pragma: no cover - defensive
            pass
        try:
            self._socket.close()
        except Exception:  # noqa: BLE001 — disconnect is best-effort  # pragma: no cover - defensive
            pass
        self.state = ProtocolState.DISCONNECTED
        self._user_wants_connected = False
        self.on_disconnect()

    # ------------------------------------------------------------------
    # Public publish / subscribe / unsubscribe
    # ------------------------------------------------------------------

    def _prefixed_topic(self, topic):
        """Resolve *topic* through the ``root_topic`` / ``client_id`` prefix scheme.

        ``root_topic=None``: return *topic* unchanged.
        ``root_topic`` set: return ``<root_topic>/<client_id>/<topic>``.
        """
        if self._root_topic is None:
            return topic
        return f"{self._root_topic}/{self._client_id}/{topic}"

    def publish(
        self,
        topic: str,
        payload: bytes | str,
        *,
        qos: int = 0,
        retain: bool = False,
        on_publish: object | None = None,
    ) -> None:
        """Queue a PUBLISH packet to a prefix-resolved topic.

        *topic* is resolved through ``root_topic`` / ``client_id``
        before going on the wire — see :meth:`_prefixed_topic`.  Use
        :meth:`publish_raw` to bypass prefixing.

        QoS 0: queued and considered delivered once it reaches the wire
        (the optional *on_publish* fires from the next :meth:`handle`).

        QoS 1: in-flight entry is opened with the packet bytes + the
        callback; PUBACK matches on packet_id and fires the callback
        exactly once.  Retries up to *publish_retry_max* on ack timeout.

        Args:
            topic: Publish topic (will be prefixed).
            payload: ``bytes`` / ``str``.  ``str`` is auto-encoded as UTF-8.
            qos: 0 or 1.  QoS 2 raises :class:`UnsupportedQoSError`.
            retain: True for retained messages.
            on_publish: Callback ``(topic, payload_bytes)`` fired on
                successful delivery.

        Raises:
            MQTTError: Client not in CONNECTED state.
        """
        self.publish_raw(
            self._prefixed_topic(topic), payload,
            qos=qos, retain=retain, on_publish=on_publish,
        )

    def publish_raw(
        self,
        topic: str,
        payload: bytes | str,
        *,
        qos: int = 0,
        retain: bool = False,
        on_publish: object | None = None,
    ) -> None:
        """Queue a PUBLISH to *topic* verbatim — no ``root_topic`` prefix.

        See :meth:`publish` for QoS / callback semantics.
        """
        if self.state != ProtocolState.CONNECTED:
            raise MQTTError(
                f"publish() requires CONNECTED state, was {self.state}",
            )
        if qos > 1:
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
            self._enqueue_user_tx(packet)
            # QoS 0 has no ack — fire the callback(s) once the bytes hit
            # the wire.  Skip the marker enqueue entirely when no callback
            # is wired, so the no-callback fast path stays single-slot.
            if on_publish is not None or self.on_publish is not _no_callback:
                self._enqueue_user_tx(
                    ("__qos0_callback__", on_publish, topic, payload_bytes),
                )
            return

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
        try:
            self._enqueue_user_tx(packet)
        except MQTTBackpressureError:
            # Roll back the in-flight allocation so the caller can retry
            # cleanly without leaking a packet_id.
            self._in_flight.discard(packet_id)
            raise

    def subscribe(
        self,
        topic: str,
        qos: int = 0,
        *,
        on_subscribe: object | None = None,
    ) -> None:
        """Queue a SUBSCRIBE for *topic*, prefix-resolved.

        *topic* is resolved through ``root_topic`` / ``client_id``
        before going on the wire.  Use :meth:`subscribe_raw` for
        topics outside the per-device hierarchy (system topics,
        bridges, wildcard pattern subscriptions).

        Args:
            topic: Topic filter (may include ``+`` / ``#`` wildcards).
                Will be prefixed.
            qos: 0 or 1.
            on_subscribe: Callback ``(topic, granted_qos)`` fired on SUBACK.

        Raises:
            MQTTError: Client not in CONNECTED state.
        """
        self.subscribe_raw(
            self._prefixed_topic(topic), qos=qos, on_subscribe=on_subscribe,
        )

    def subscribe_raw(
        self,
        topic: str,
        qos: int = 0,
        *,
        on_subscribe: object | None = None,
    ) -> None:
        """Queue a SUBSCRIBE for *topic* verbatim — no ``root_topic`` prefix."""
        if self.state != ProtocolState.CONNECTED:
            raise MQTTError(
                f"subscribe() requires CONNECTED state, was {self.state}",
            )
        packet_id = self._in_flight.allocate_id()  # Reuse the id pool.
        packet = encode_subscribe(
            packet_id=packet_id, subscriptions=[(topic, qos)],
        )
        self._enqueue_user_tx(packet)

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
        """Queue an UNSUBSCRIBE for *topic*, prefix-resolved.

        Mirror of :meth:`subscribe` — use :meth:`unsubscribe_raw` to
        bypass prefixing.
        """
        self.unsubscribe_raw(
            self._prefixed_topic(topic), on_unsubscribe=on_unsubscribe,
        )

    def unsubscribe_raw(self, topic, *, on_unsubscribe=None):
        """Queue an UNSUBSCRIBE for *topic* verbatim — no ``root_topic`` prefix."""
        if self.state != ProtocolState.CONNECTED:
            raise MQTTError(
                f"unsubscribe() requires CONNECTED state, was {self.state}",
            )
        packet_id = self._in_flight.allocate_id()
        packet = encode_unsubscribe(packet_id=packet_id, topics=[topic])
        self._enqueue_user_tx(packet)

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

    def publisher(self, topic, *, qos=0, retain=False):
        """Return an :class:`MQTTPublisher` bound to *topic* / *qos* / *retain*.

        The bound topic resolves through :meth:`_prefixed_topic` on
        each publish — the same as :meth:`publish` itself.  For
        unprefixed publishing, call :meth:`publish_raw` directly.
        """
        return MQTTPublisher(self, topic, qos=qos, retain=retain)

    def add_pattern_handler(self, pattern, handler):
        """Register *handler* ``(topic, payload_bytes)`` for inbound messages matching *pattern*.

        Splits the pattern once at registration so the per-inbound-
        message dispatch only splits the topic, not the pattern.

        Inbound topics are matched against patterns verbatim — patterns
        are **not** ``root_topic``-prefixed.  Pass the prefixed pattern
        directly if you want per-device-only routing.
        """
        self._pattern_handlers.append((tuple(pattern.split("/")), handler))

    def remove_pattern_handler(self, handler, pattern=None):
        """Remove *handler* from the pattern-handler list.

        ``pattern=None`` (default) removes every registration of
        *handler* across all patterns.  Pass *pattern* to remove only
        the registration matching that pattern.
        """
        if pattern is None:
            self._pattern_handlers = [
                (registered_pattern, registered_handler)
                for registered_pattern, registered_handler in self._pattern_handlers
                if registered_handler is not handler
            ]
            return
        pattern_levels = tuple(pattern.split("/"))
        self._pattern_handlers = [
            (registered_pattern, registered_handler)
            for registered_pattern, registered_handler in self._pattern_handlers
            if not (registered_pattern == pattern_levels and registered_handler is handler)
        ]

    # ------------------------------------------------------------------
    # Runner contract
    # ------------------------------------------------------------------

    def check(self, now_ms):  # noqa: ARG002 — runner contract uses now_ms
        """Return ``True`` when the client wants a ``handle()`` this tick.

        The recv path is cooperative — ``handle()`` always attempts a
        non-blocking recv and bails on EAGAIN — so any non-terminal
        state is worth a tick.
        """
        return self.state not in (ProtocolState.DISCONNECTED, ProtocolState.FAILED)

    def handle(self, now_ms):
        """One tick of progress.

        Drains the TX queue first, then pulls inbound bytes into the
        decoder and processes any complete packets, then checks ack
        deadlines + keepalive timer.  Drains TX again at the end —
        deadline-retry PUBLISHes and PINGREQs queued by the deadline
        + keepalive checks would otherwise wait an extra tick.

        When the client is in ``FAILED`` and a ``socket_factory`` is
        configured + the user originally called ``connect()``, this
        tick attempts a self-heal: rebuild the socket via the factory,
        reset internal queues, transition back to ``DISCONNECTED``,
        and re-issue ``connect()``.  The factory failing (typically
        because wifi is still down) leaves the client in ``FAILED``
        and the next tick retries — naturally rate-limited by the
        runner's tick cadence.

        *now_ms* is the per-tick timestamp the runner captured once
        and passes to every registered service so they all see the
        same instant — the runner contract.  Callers must source it
        from ``chumicro_timing.ticks_ms()`` (or the matching method on
        the injected ``ticks`` object) so the value is in the same
        domain as the deadlines this client computed at ``connect()`` /
        ``publish()`` time.  ``chumicro-runner.Runner`` handles this
        automatically; tests that roll their own poll loops must do
        the same.
        """
        if self.state == ProtocolState.FAILED:
            if self._socket_factory is None or not self._user_wants_connected:
                return
            if not self._attempt_self_heal():
                return
            # Self-heal succeeded — fall through and tick the new connection.
        if self.state == ProtocolState.DISCONNECTED:
            return
        try:
            self._drain_tx_queue()
            self._read_inbound(now_ms)
            self._check_deadlines(now_ms)
            self._check_keepalive(now_ms)
            self._drain_tx_queue()
        except MQTTError as error:
            self.last_error = error
            self.state = ProtocolState.FAILED
        except OSError as error:
            self.last_error = MQTTError(f"socket error: {error}")
            self.state = ProtocolState.FAILED

    def _attempt_self_heal(self):
        """Rebuild the socket via ``socket_factory`` and re-issue connect.

        Best-effort — if the factory raises (typically because wifi is
        still down) the client stays in ``FAILED`` and the next handle
        tick retries.

        Returns ``True`` when self-heal succeeded and the client is
        ready to tick (in ``CONNECTING``); ``False`` when the factory
        failed and the client is still ``FAILED``.
        """
        # Close the dead socket best-effort so we don't leak file descriptors
        # on long-running boards.
        try:
            if self._socket is not None:
                self._socket.close()
        except OSError:  # pragma: no cover - defensive
            pass
        try:
            new_socket = self._socket_factory()
        except OSError as factory_error:
            self.last_error = MQTTError(
                f"socket factory failed: {factory_error}",
            )
            return False
        self._socket = new_socket
        _force_non_blocking(self._socket)
        # Reset transient state for the fresh connection.  Keep the
        # in-flight QoS 1 table intact when clean_session=False so a
        # broker that supports session resumption can pick up where we
        # left off; clear it on clean_session=True (the safer default).
        # Reassign rather than calling .clear() — MicroPython's deque
        # does not implement clear() (verified on MP 1.26 + CP 10.x).
        self._tx_queue = _new_tx_queue(self._max_tx_queue_size + 64)
        self._partial_send = None
        self._pending_responses.clear()
        # Fresh decoder — discards any partial inbound packet from the
        # dead socket and resets the degraded-buffer state.
        self._decoder = PacketDecoder(**self._decoder_kwargs)
        if self._clean_session:
            self._in_flight = InFlightTable()
        self.state = ProtocolState.DISCONNECTED
        self.last_error = None
        # Re-issue connect — this transitions to CONNECTING and queues
        # the CONNECT packet that the upcoming _drain_tx_queue() flushes.
        self.connect()
        return True

    # ------------------------------------------------------------------
    # Internal — TX path
    # ------------------------------------------------------------------

    def _drain_tx_queue(self):
        """Send queued packets until the socket would block.

        Each item is either ``bytes`` (a packet) or a
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
                self._tx_queue.popleft()
                if callback is not None:
                    callback(topic, payload)
                self.on_publish(topic, payload)
                continue
            packet = head
            sent = self._send_raw(packet)
            if sent <= 0:  # pragma: no cover - non-blocking-EAGAIN backpressure path
                return  # Socket would block — wait for next tick.
            if sent < len(packet):  # pragma: no cover - rare partial-send path
                self._partial_send = (packet, sent)
                self._tx_queue.popleft()
                return
            self._tx_queue.popleft()

    def _send_raw(self, payload):
        """Send *payload*; return bytes sent (may be 0 on EAGAIN)."""
        try:
            return self._socket.send(payload)
        except OSError as error:
            if _is_eagain(error):  # pragma: no cover - EAGAIN handling
                return 0
            raise

    def _enqueue_user_tx(self, item):
        """Append a user-initiated packet/marker to the TX queue, honoring the cap.

        Raises :class:`MQTTBackpressureError` when the queue is full
        — the caller's signal to drain via :meth:`handle` and retry.
        Internal protocol packets (PUBACK responses, deadline-triggered
        retransmits, PINGREQ) bypass this cap because failing to enqueue
        them would break QoS-1 / keepalive guarantees; the cap exists
        to catch a runaway publisher, not to block protocol bookkeeping.
        """
        if len(self._tx_queue) >= self._max_tx_queue_size:
            raise MQTTBackpressureError(
                f"tx queue full ({len(self._tx_queue)} >= "
                f"{self._max_tx_queue_size}); call handle() to drain "
                "and retry",
            )
        self._tx_queue.append(item)

    # ------------------------------------------------------------------
    # Internal — RX path
    # ------------------------------------------------------------------

    def _read_inbound(self, now_ms):
        """Pull bytes off the socket; process complete packets.

        Doesn't short-circuit on "got < capacity" — TCP can fragment
        a single broker burst across multiple recv calls.  But the
        pull loop *is* bounded per tick by ``recv_budget_per_tick``
        (default 1024 B): a 100 KB inbound PUBLISH would otherwise
        monopolize the tick while the kernel TCP buffer drains, and
        side tasks like LED blink / LCD update would stutter.  With
        the cap, a big blob takes more ticks to ingest but every
        tick stays short.

        The cap applies whether we're in the steady-state RX path or
        the degraded-buffer (oversized) path — both feed through
        the same ``recv_into`` calls.
        """
        consumed = 0
        budget = self._recv_budget_per_tick
        while consumed < budget:
            buffer_view = self._decoder.fill_buffer()
            capacity = self._decoder.fill_capacity()
            if capacity <= 0:
                break  # pragma: no cover - decoder full; let the parser drain.
            # Don't read past the per-tick budget.
            if capacity > budget - consumed:
                capacity = budget - consumed
                buffer_view = buffer_view[:capacity]
            try:
                got = self._socket.recv_into(buffer_view, capacity)
            except OSError as error:
                if _is_eagain(error):  # pragma: no cover - EAGAIN handling
                    break  # EAGAIN — no data this tick.
                raise
            if got == 0:
                break  # Peer closed or no data this tick.
            self._decoder.advance(got)
            consumed += got

        while True:
            packet = self._decoder.read_next()
            if packet is None:
                break
            if isinstance(packet, ParsedPublish):
                self._handle_inbound_publish(packet)
            elif isinstance(packet, _OversizedMessage):
                self._handle_oversized(packet)
            elif isinstance(packet, ParsedAck):
                self._handle_ack(packet, now_ms)

    def _handle_inbound_publish(self, packet):
        """Fire callbacks + (for QoS 1) send PUBACK."""
        # Pattern handlers fire before the global on_message.  Split
        # the topic once and reuse for every registered pattern.
        if self._pattern_handlers:
            topic_levels = packet.topic.split("/")
            for pattern_levels, handler in self._pattern_handlers:
                if _topic_levels_match(topic_levels, pattern_levels):
                    handler(packet.topic, packet.payload)
        self.on_message(packet.topic, packet.payload)
        if packet.qos == 1:
            self._tx_queue.appendleft(encode_puback(packet_id=packet.packet_id))

    def _handle_oversized(self, packet):
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
        # PUBACK QoS 1 oversized messages even when dropping payload —
        # broker would otherwise retransmit.
        if packet.qos == 1 and self._when_oversized != WhenOversized.DISCONNECT:
            self._tx_queue.appendleft(encode_puback(packet_id=packet.packet_id))

    def _handle_ack(self, packet, now_ms):
        """Match an inbound ack to its pending entry; PINGRESP is tolerated.

        An unmatched PUBACK / SUBACK / UNSUBACK faults to FAILED — a
        broker that ACKs a packet_id we never issued is a real bug.
        PINGRESP is racy in keepalive-timeout / self-heal corners
        and silently ignored.
        """
        if packet.packet_type == PACKET_CONNACK:
            self._handle_connack(packet, now_ms)
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
            # MQTT 3.1.1 §3.9.3: granted_qos byte 0x80 (== 128)
            # signals "Failure" — broker rejected the subscription
            # (ACL deny, topic-not-permitted, etc.).  Surface as a
            # protocol error so the application sees the failure
            # instead of silently inheriting a never-matched
            # subscription.
            if packet.granted_qos and 0x80 in packet.granted_qos:
                raise MQTTProtocolError(
                    f"SUBACK rejection (packet_id {packet.packet_id}, "
                    f"granted_qos {packet.granted_qos}) — broker refused "
                    "one or more subscription filters"
                )
            matched = self._discard_pending(
                Awaiting.SUBACK,
                packet_id=packet.packet_id,
                callback_arg=packet.granted_qos,
            )
            self._in_flight.discard(packet.packet_id)  # Free the id.
            if not matched:
                raise MQTTProtocolError(
                    f"SUBACK for unknown packet_id {packet.packet_id}",
                )
            return
        if packet.packet_type == PACKET_UNSUBACK:
            matched = self._discard_pending(
                Awaiting.UNSUBACK, packet_id=packet.packet_id, callback_arg=None,
            )
            self._in_flight.discard(packet.packet_id)
            if not matched:
                raise MQTTProtocolError(
                    f"UNSUBACK for unknown packet_id {packet.packet_id}",
                )
            return

    def _handle_connack(self, packet, now_ms):
        """CONNACK return-code 0 = success, anything else = failure."""
        self._discard_pending(Awaiting.CONNACK, packet_id=None)
        if packet.return_code != 0:
            # MQTT 3.1.1 §3.2.2.3 — codes 1-5 are the rejection codes a
            # broker may send.  Built inline so the dict only allocates
            # on rejection (rare); the success path never touches it.
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
            self.state = ProtocolState.FAILED
            return
        self.state = ProtocolState.CONNECTED
        self._next_ping_due_ticks = self._deadline(self._ping_interval_ms, now_ms=now_ms)
        self.on_connect()

    def _discard_pending(self, awaiting, *, packet_id, callback_arg=None):
        """Find + remove the matching :class:`PendingResponse`; fire callback.

        Returns ``True`` when a match was found and removed; ``False``
        when no matching pending entry exists (caller decides whether
        that's a protocol fault or a tolerated late arrival).
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
            return True
        return False

    # ------------------------------------------------------------------
    # Internal — deadlines + keepalive
    # ------------------------------------------------------------------

    def _check_deadlines(self, now_ms):
        """Retry / fault on expired in-flight + pending entries."""
        # ``list()`` wraps are needed only to allow safe mutation inside
        # the loop body (``discard`` / ``remove``); skip allocating the
        # copy when the underlying collection is empty — the common
        # steady-state on a sensor-profile publisher.
        if self._in_flight:
            for entry in list(self._in_flight):
                if self._ticks.ticks_diff(entry.deadline_ticks, now_ms) > 0:
                    continue
                if entry.retry_count >= self._publish_retry_max:
                    self._in_flight.discard(entry.packet_id)
                    self.last_error = MQTTError(
                        f"PUBLISH packet_id {entry.packet_id} exceeded "
                        f"retry limit {self._publish_retry_max}",
                    )
                    self.state = ProtocolState.FAILED
                    return
                entry.retry_count += 1
                entry.deadline_ticks = self._deadline(self._ack_timeout_ms, now_ms=now_ms)
                # Set the DUP flag (bit 3 of byte 0) per MQTT 3.1.1 §4.3.2.
                retry_packet = bytearray(entry.packet_bytes)
                retry_packet[0] |= 0x08
                self._tx_queue.append(bytes(retry_packet))

        if self._pending_responses:
            for pending in list(self._pending_responses):
                if self._ticks.ticks_diff(pending.deadline_ticks, now_ms) > 0:
                    continue
                self._pending_responses.remove(pending)
                self.last_error = MQTTError(
                    f"timed out awaiting {pending.awaiting}",
                )
                self.state = ProtocolState.FAILED
                return

    def _check_keepalive(self, now_ms):
        """Send a PINGREQ when half the keepalive interval has elapsed."""
        if self.state != ProtocolState.CONNECTED:
            return
        if self._ticks.ticks_diff(self._next_ping_due_ticks, now_ms) > 0:
            return
        # Already awaiting a PINGRESP?  Don't double-send.
        for pending in self._pending_responses:
            if pending.awaiting == Awaiting.PINGRESP:
                return
        self._tx_queue.append(PACKET_PINGREQ)
        self._pending_responses.append(
            PendingResponse(
                awaiting=Awaiting.PINGRESP,
                deadline_ticks=self._deadline(self._ack_timeout_ms, now_ms=now_ms),
            ),
        )
        self._next_ping_due_ticks = self._deadline(self._ping_interval_ms, now_ms=now_ms)

    def _deadline(self, offset_ms, *, now_ms=None):
        """Return a tick value that's *offset_ms* in the future.

        When called from inside a ``handle()`` path, pass the runner-
        supplied *now_ms* so the deadline is armed against the same
        tick the surrounding code is comparing against — one ``ticks_ms``
        per tick, shared across every deadline computed that tick.
        User-entry callers (``connect``, ``publish``, ``subscribe``,
        ``unsubscribe``) run outside the tick loop and pass nothing,
        so a fresh ``ticks_ms()`` is captured.
        """
        if now_ms is None:
            now_ms = self._ticks.ticks_ms()
        return self._ticks.ticks_add(now_ms, offset_ms)
