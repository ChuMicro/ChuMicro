"""MQTT 3.1.1 client built on chumicro-sockets + chumicro-timing.

:class:`MQTTClient` is the public entry point.
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

# Poll-interest bits mirroring chumicro_runner.IO_READ / IO_WRITE by value,
# held as literals so the client takes no dependency edge on the runner.
_IO_READ = 1
_IO_WRITE = 2


class ProtocolState:
    """Connection lifecycle states."""

    DISCONNECTED = "disconnected"
    AWAITING_TRANSPORT = "awaiting_transport"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"


class InboundPublish:
    """One inbound PUBLISH returned by :meth:`MQTTClient.next_message`."""

    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload

    def __repr__(self):
        return f"InboundPublish(topic={self.topic!r}, {len(self.payload)} bytes)"


class _InboundWait:
    # io_socket=None: the client polls its own socket; this wait just re-checks the queue.
    io_socket = None


_INBOUND_WAIT = _InboundWait()


_AWAIT_CONNACK = "connack"
_AWAIT_PINGRESP = "pingresp"
_AWAIT_PUBACK = "puback"
_AWAIT_SUBACK = "suback"
_AWAIT_UNSUBACK = "unsuback"

_SELF_HEAL_BACKOFF_BASE_MS = 1000
_SELF_HEAL_BACKOFF_CAP_MS = 60000

# CONNACK codes retrying can't fix: bad protocol version (1), identifier
# rejected (2), bad credentials (4), not authorized (5). Code 3 stays transient.
_PERMANENT_CONNACK_CODES = (1, 2, 4, 5)

_MAX_INBOUND_QUEUE_SIZE = 16


class InFlightPublish:
    """One outstanding QoS 1 PUBLISH awaiting a PUBACK."""

    def __init__(self, packet_id, packet_bytes, deadline_ticks, callback=None):
        self.packet_id = packet_id
        self.packet_bytes = packet_bytes
        self.retry_count = 0
        self.deadline_ticks = deadline_ticks
        self.callback = callback
        self.dup_packet_bytes = None


class PendingResponse:
    """A non-publish response we're waiting for (CONNACK / SUBACK / UNSUBACK / PINGRESP)."""

    def __init__(self, awaiting, deadline_ticks, packet_id=None, callback=None, topic=None):
        self.awaiting = awaiting
        self.deadline_ticks = deadline_ticks
        self.packet_id = packet_id
        self.callback = callback
        self.topic = topic


class WhenOversized:
    """Policy for inbound PUBLISH whose total wire size exceeds ``rx_buffer_size``."""

    #: Drop the payload silently and PUBACK the broker.
    DROP_SILENT = "drop_silent"

    #: Default. Drop the payload, fire ``on_oversized(reported_length, topic)``, still PUBACK.
    DROP_WITH_EVENT = "drop_with_event"

    #: Treat as a protocol error and disconnect.
    DISCONNECT = "disconnect"


def _no_callback(*_args, **_kwargs):
    return None


def _new_tx_queue(maxlen):
    # MicroPython/CircuitPython need flags=1 for appendleft; CPython rejects
    # the third arg, so try the embedded shape and fall back.
    try:
        return deque((), maxlen, 1)
    except TypeError:
        return deque((), maxlen)


def _force_non_blocking(socket):
    # Some MicroPython TLS adapters lack setblocking, so probe and tolerate it.
    setblocking = getattr(socket, "setblocking", None)
    if setblocking is None:
        return
    try:
        setblocking(False)
    except (OSError, AttributeError):  # pragma: no cover - defensive
        pass


def default_client_id(prefix="chumicro"):
    """Return a stable per-device MQTT client id ``<prefix>-<uid-hex>``.

    Unique across devices, stable across reboots (so a persistent session
    resumes rather than colliding on a shared broker).  The UID comes from
    ``microcontroller.cpu.uid`` (CircuitPython), ``machine.unique_id()``
    (MicroPython), or the host MAC via ``uuid.getnode()`` (CPython); each is
    guarded, and if none works the historical ``<prefix>-mqtt`` is returned.
    """
    guarded = (ImportError, AttributeError, OSError, NotImplementedError)
    uid = None
    try:
        import microcontroller  # noqa: PLC0415 - CircuitPython, import-guarded
        uid = bytes(microcontroller.cpu.uid)
    except guarded:
        try:
            import machine  # noqa: PLC0415 - MicroPython, import-guarded
            uid = bytes(machine.unique_id())
        except guarded:
            try:
                import uuid  # noqa: PLC0415 - CPython standard library
                uid = uuid.getnode().to_bytes(6, "big")
            except guarded:
                uid = None
    if not uid:
        return prefix + "-mqtt"
    return prefix + "-" + "".join(f"{byte:02x}" for byte in uid)


class MQTTClient:
    """Non-blocking MQTT 3.1.1 client (QoS 0 + 1)."""

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
            # Lazy import so callers who pass their own socket/transport_factory
            # never pull chumicro_sockets into the deploy graph.
            try:
                from chumicro_sockets.sockets_factory import (  # noqa: PLC0415 - lazy
                    fixed_connector_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_sockets.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or "
                    "not on the board); pass transport_factory= or "
                    "socket= explicitly.",
                ) from exception

            from chumicro_config import MissingConfigKey  # noqa: PLC0415 - lazy

            for required_key in ("mqtt.broker.host", "mqtt.broker.port"):
                if required_key not in config:
                    raise MissingConfigKey(
                        f"required config key {required_key!r} is missing",
                    )
            transport_factory = fixed_connector_factory(
                config["mqtt.broker.host"], config["mqtt.broker.port"],
                radio=radio, ssl_context=ssl_context,
            )
        return cls(
            socket=socket,
            transport_factory=transport_factory,
            client_id=config.get("mqtt.client_id") or default_client_id(),
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
            socket: Already-connected non-blocking socket; ``None`` when *transport_factory* is given.
            transport_factory: Zero-arg ``SocketConnector`` factory; used when *socket* is ``None``.
            client_id: MQTT client identifier, unique per broker.
            keep_alive_seconds: Broker idle timeout; PINGREQ runs at half this interval.
            ack_timeout_seconds: Per-ack deadline, also bounding each transport attempt.
            publish_retry_max: Max QoS 1 PUBLISH retries before FAILED.
            username: Optional auth username.
            password: Optional auth password.
            clean_session: ``False`` resumes persistent broker session state across reconnects.
            will_topic: Last-will topic; ``None`` disables the will.
            will_message: Last-will payload.
            will_qos: Will QoS (0 or 1).
            will_retain: ``True`` retains the will on the broker.
            rx_buffer_size: Steady-state RX buffer (default 256); larger PUBLISHes use the oversized tier.
            when_oversized: Policy for inbound messages larger than ``rx_buffer_size``.
            when_disconnected: :meth:`publish` policy before CONNECTED, ``"queue"`` (default) or ``"raise"``.
            pre_connect_queue_size: Bound on the pre-connect publish queue (default 8).
            recv_budget_per_tick: Cap on bytes pulled per tick (default 1024).
            max_tx_queue_size: Maximum pending outbound packets (default 20).
            send_timeout_seconds: Max unsent time before FAILED; ``None`` inherits *ack_timeout_seconds*.
            ticks: Optional tick source (``chumicro_timing.ticks`` shape); defaults to the real clock.
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
        self._in_flight = {}
        self._next_packet_id = 1
        self._pending_responses = []
        # topic -> [requested_qos, one-shot on_subscribe]; slot 1 fires on the
        # first SUBACK granting the topic, then clears.
        self._subscriptions = {}
        # 64-slot headroom above the user cap so QoS-1 retries and PINGREQ
        # can't be lost when the user queue is full.
        self._tx_queue_hard_cap = max_tx_queue_size + 64
        self._tx_queue = _new_tx_queue(self._tx_queue_hard_cap)
        self._partial_send = None  # (memoryview, offset) when the last send was short.
        self._pending_pubacks = []
        self._puback_batch_queued = False
        self._send_deadline_ticks = None

        self._next_ping_due_ticks = 0
        # keep_alive_seconds == 0 disables keepalive (MQTT 3.1.1 §3.1.2.10);
        # otherwise ping at half the interval, floored at 1 s.
        self._keepalive_enabled = keep_alive_seconds > 0
        self._ping_interval_ms = max(1000, keep_alive_seconds * 1000 // 2)

        # Callbacks default to no-ops so handlers fire without a None check.
        self.on_message = _no_callback
        self.on_connect = _no_callback
        self.on_disconnect = _no_callback
        self.on_subscribe = _no_callback
        self.on_unsubscribe = _no_callback
        self.on_publish = _no_callback
        self.on_oversized = _no_callback
        self._inbound_queue = None
        self.last_error = None
        self._self_heal_attempts = 0
        self._self_heal_retry_at_ticks = None
        self._permanent_failure = False
        self._reconnect_held = False

    def connect(self):
        """Express the intent "be connected", acting on it now."""
        self._reconnect_held = False
        self._user_wants_connected = True
        if self.state == ProtocolState.DISCONNECTED:
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
            self._permanent_failure = False
            self._self_heal_attempts = 0
            self._self_heal_retry_at_ticks = None
            return

    def hold(self):
        """Suspend timer-driven reconnection until the next :meth:`connect`."""
        self._reconnect_held = True

    def _enqueue_connect_packet(self):
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
        """Queue a DISCONNECT packet, close the socket, mark DISCONNECTED."""
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
        # Null the socket so a later connect() routes through the factory, not the closed fd.
        self._socket = None
        self._reset_transient_state()
        # Deliberate disconnect drops buffered publishes; self-heal keeps them.
        self._pre_connect_queue = _new_tx_queue(self._pre_connect_queue_size)
        self.state = ProtocolState.DISCONNECTED
        self._user_wants_connected = False
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
            topic: Will topic; ``None`` disables the will.
            message: Will payload; ``None`` becomes empty bytes.
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

        Args:
            topic: Publish topic, sent on the wire as written.
            payload: ``bytes`` or ``str`` (``str`` is auto-encoded as UTF-8).
            qos: 0 or 1; QoS 2 raises :class:`UnsupportedQoSError`.
            retain: ``True`` for retained messages.
            on_publish: Callback ``(topic, payload_bytes)`` fired on delivery.

        Raises:
            MQTTError: ``when_disconnected="raise"`` and not yet CONNECTED.
            MQTTBackpressureError: The tx queue or pre-connect queue is full.
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
            raise MQTTBackpressureError(
                f"pre-connect publish queue full "
                f"({self._pre_connect_queue_size}); call handle() to "
                "connect and drain, then retry",
            )
        queue.append((topic, payload_bytes, qos, retain, on_publish))

    def _drain_pre_connect_queue(self):
        queue = self._pre_connect_queue
        while queue:
            topic, payload_bytes, qos, retain, on_publish = queue.popleft()
            self._do_publish(topic, payload_bytes, qos, retain, on_publish)

    def _do_publish(self, topic, payload_bytes, qos, retain, on_publish):
        if qos == 0:
            packet = encode_publish(
                topic=topic, payload=payload_bytes, qos=0, retain=retain,
            )
            # QoS 0 has no ack: on_publish fires via a marker entry enqueued
            # with the packet as one unit so the pair can't half-land.
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

        # _allocate_packet_id refuses live ids; this guards a future refactor.
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
            # Roll back the in-flight entry so a full queue doesn't leak a packet_id.
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

        Args:
            topic: Topic filter (``+`` / ``#`` wildcards ok), sent as written.
            qos: 0 or 1.
            on_subscribe: One-shot ``(topic, granted_qos)`` fired on the first SUBACK granting *topic*.

        Raises:
            MQTTBackpressureError: Already CONNECTED and the tx queue is full.
        """
        def _wrapped(granted_qos):
            if on_subscribe is not None:
                on_subscribe(topic, granted_qos)
            self.on_subscribe(topic, granted_qos)

        # Send before recording, so a full-queue error leaves the desired set untouched.
        if self.state == ProtocolState.CONNECTED:
            packet_id = self._allocate_packet_id()
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
        """Retract a subscription for *topic*, valid in any state."""
        if self.state != ProtocolState.CONNECTED:
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
        """Suspend until the next inbound PUBLISH; return it, or ``None`` when parked."""
        if self._inbound_queue is None:
            # 2-arg deque drops the oldest when full, unlike the raising TX queue.
            self._inbound_queue = deque((), _MAX_INBOUND_QUEUE_SIZE)
        while True:
            if self._inbound_queue:
                return self._inbound_queue.popleft()
            if self._inbound_stream_ended():
                return None
            yield _INBOUND_WAIT

    def _inbound_stream_ended(self):
        if self.state == ProtocolState.DISCONNECTED:
            return True
        if self.state != ProtocolState.FAILED:
            return False
        return (
            self._transport_factory is None
            or not self._user_wants_connected
            or self._permanent_failure
        )

    def check(self, now_ms):  # noqa: ARG002 (runner contract uses now_ms)
        """Return ``True`` when the client wants a ``handle()`` this tick."""
        if self.state == ProtocolState.FAILED and (
            self._permanent_failure or self._reconnect_held
        ):
            return False
        return self.state is not ProtocolState.DISCONNECTED

    @property
    def io_socket(self):
        """The MQTT socket-ish object while connected, connecting, or bringing up transport, else ``None``."""
        if self.state == ProtocolState.AWAITING_TRANSPORT:
            return self._connector.io_socket if self._connector is not None else None
        if self._socket is None:
            return None
        if self.state in (ProtocolState.DISCONNECTED, ProtocolState.FAILED):
            return None
        return self._socket

    def io_interest(self, now_ms):
        """Poll-interest bitmask (``_IO_READ`` / ``_IO_WRITE``) for ``Runner.wait``."""
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
        """Runner hook: POLLERR / POLLHUP surfaced on the registered socket."""
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
        """Earliest tick at which ``handle()`` must run even on a quiet socket."""
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
        """One tick of progress."""
        if self.state == ProtocolState.FAILED:
            if not self._self_heal_active():
                return
            if (
                self._self_heal_retry_at_ticks is not None
                and self._ticks.ticks_diff(self._self_heal_retry_at_ticks, now_ms) > 0
            ):
                return
            self._arm_self_heal_backoff(now_ms)
            if not self._attempt_self_heal(now_ms):
                return
            # Self-heal succeeded; fall through to tick the connector this same tick.
        if self.state == ProtocolState.AWAITING_TRANSPORT:
            # Check the deadline before advancing, so a stalled attempt faults promptly.
            if self._check_transport_deadline(now_ms):
                return
            if not self._advance_connector(now_ms):
                return
        if self.state == ProtocolState.DISCONNECTED:
            return
        try:
            # Timeouts first so a wedged recv can't block deadline detection.
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
        return (
            self._transport_factory is not None
            and self._user_wants_connected
            and not self._permanent_failure
            and not self._reconnect_held
        )

    def _arm_self_heal_backoff(self, now_ms):
        # Exponential backoff, doubling per attempt. Clamp the shift at 6 so a
        # long outage doesn't grow a big-int (6 doublings already exceed the cap).
        if self._self_heal_attempts >= 6:
            delay_ms = _SELF_HEAL_BACKOFF_CAP_MS
        else:
            delay_ms = _SELF_HEAL_BACKOFF_BASE_MS << self._self_heal_attempts
            if delay_ms > _SELF_HEAL_BACKOFF_CAP_MS:
                delay_ms = _SELF_HEAL_BACKOFF_CAP_MS
            self._self_heal_attempts += 1
        self._self_heal_retry_at_ticks = self._deadline(delay_ms, now_ms=now_ms)

    def _attempt_self_heal(self, now_ms):
        # Close the dead socket best-effort so we don't leak a file descriptor.
        try:
            if self._socket is not None:
                self._socket.close()
        except OSError:  # pragma: no cover - defensive
            pass
        self._socket = None
        # clean_session=False may resume the broker session, so keep the
        # in-flight QoS 1 table; clear it when clean_session=True.
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
        # Connectors never time out on their own, so this faults a black-holed connect.
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

    def _allocate_packet_id(self):
        # Next free id in the 1-65535 cycle (id 0 is spec-reserved).
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

    def _drain_tx_queue(self):
        # One packet per tick so other runner services get CPU; a PUBACK batch
        # at the head bypasses that budget so acks track inbound dispatch.
        # Resume a partial send first: its remainder must land before any new packet.
        if self._partial_send is not None:  # pragma: no cover - rare partial-send recovery path
            packet, offset = self._partial_send
            sent = self._send_raw(packet[offset:])
            new_offset = offset + sent
            if new_offset >= len(packet):
                self._partial_send = None
            else:
                self._partial_send = (packet, new_offset)
            self._update_send_deadline(sent)
            return

        while True:
            self._drain_callback_markers()
            if not self._tx_queue:
                self._update_send_deadline(0)
                return
            packet = self._tx_queue[0]
            is_puback_batch = packet[0] == PACKET_PUBACK
            sent = self._send_raw(packet)
            if sent <= 0:  # pragma: no cover - non-blocking-EAGAIN backpressure path
                self._update_send_deadline(0)
                return
            if sent < len(packet):  # pragma: no cover - rare partial-send path
                # memoryview so the resume path slices zero-copy; bytes are safe to hold across ticks.
                self._partial_send = (memoryview(packet), sent)
                self._tx_queue.popleft()
                if is_puback_batch:
                    # Unsent tail still owes acks; the partial send keeps recv suppressed.
                    self._puback_batch_queued = False
                self._update_send_deadline(sent)
                return
            self._tx_queue.popleft()
            self._update_send_deadline(sent)
            if is_puback_batch:
                self._puback_batch_queued = False
                continue  # PUBACK flush spent no packet budget; keep draining.
            # Drain trailing QoS 0 markers so on_publish fires this tick, not next.
            self._drain_callback_markers()
            return

    def _update_send_deadline(self, bytes_sent):
        # Re-arm on progress so a steady drip doesn't false-fail; on no
        # progress keep the running timer so a stall eventually trips.
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
        try:
            return self._socket.send(payload)
        except OSError as error:
            if error.errno == errno.EAGAIN:  # pragma: no cover - EAGAIN handling
                return 0
            raise

    def _enqueue_user_tx(self, *items):
        # Append the items as a unit under the user cap so a QoS-0 packet and
        # its callback marker can't half-land.
        if len(self._tx_queue) + len(items) > self._max_tx_queue_size:
            raise MQTTBackpressureError(
                f"tx queue full ({len(self._tx_queue)} + {len(items)} > "
                f"{self._max_tx_queue_size}); call handle() to drain "
                "and retry",
            )
        for item in items:
            self._tx_queue.append(item)

    def _enqueue_internal_tx(self, packet, *, front=False):
        # Queue a protocol packet in the headroom above the user cap; returns
        # False at the hard cap. front=True queues ahead of user packets.
        if len(self._tx_queue) >= self._tx_queue_hard_cap:
            return False
        if front:
            self._tx_queue.appendleft(packet)
        else:
            self._tx_queue.append(packet)
        return True

    def _recv_suppressed(self):
        # Pause recv while acks or a partial send are pending: unread bytes
        # stay in the kernel, closing the TCP window to throttle the broker.
        return self._puback_batch_queued or self._partial_send is not None

    def _read_inbound(self, now_ms):
        # One recv_into per tick, then dispatch all buffered packets; skip
        # while suppressed so acks don't pile up and stay in receipt order.
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
                    got = 0
                else:
                    raise
            else:
                if got == 0:
                    # recv_into returning 0 is a clean peer FIN (no data raises
                    # EAGAIN); raise so handle() faults to FAILED.
                    raise MQTTProtocolError("broker closed connection")
                self._decoder.advance(got)

        # Coalesce this tick's PUBACKs into one batch, kept in receipt order
        # (MQTT-4.6.0-2).
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
            # An inbound callback may have disconnected; stop dispatching if so.
            if self.state != ProtocolState.CONNECTED:
                return
        # Flush as one front-of-queue entry; a full hard cap faults rather than
        # drop a PUBACK, since a lost ack corrupts the stream.
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
        pending_pubacks.clear()

    def _handle_inbound_publish(self, packet, pending_pubacks):
        if self._inbound_queue is not None:
            self._inbound_queue.append(
                InboundPublish(packet.topic, packet.payload),
            )
        else:
            self.on_message(packet.topic, packet.payload)
        if packet.qos == 1:
            pending_pubacks.append(encode_puback(packet_id=packet.packet_id))

    def _handle_oversized(self, packet, pending_pubacks):
        if self._when_oversized == WhenOversized.DROP_SILENT:
            pass
        elif self._when_oversized == WhenOversized.DROP_WITH_EVENT:
            self.on_oversized(packet.reported_length, packet.topic)
        elif self._when_oversized == WhenOversized.DISCONNECT:
            raise MQTTProtocolError(
                f"oversized message on topic {packet.topic!r} "
                f"({packet.reported_length} bytes)",
            )
        # PUBACK a QoS-1 oversize so the broker stops retransmitting, but only
        # when packet_id survived (an oversize topic yields None, unackable).
        if (
            packet.qos == 1
            and packet.packet_id is not None
            and self._when_oversized != WhenOversized.DISCONNECT
        ):
            pending_pubacks.append(encode_puback(packet_id=packet.packet_id))

    def _handle_ack(self, packet, now_ms):
        # Dispatch by type; an unmatched ack faults, a stray PINGRESP is tolerated.
        if packet.packet_type == PACKET_CONNACK:
            self._handle_connack(packet, now_ms)
            return
        if packet.packet_type == PACKET_PINGRESP:
            self._discard_pending(_AWAIT_PINGRESP, packet_id=None)
            return
        if packet.packet_type == PACKET_PUBACK:
            in_flight = self._in_flight.pop(packet.packet_id, None)
            if in_flight is None:
                # Usually a duplicate PUBACK (our publish plus its DUP retransmit);
                # tolerate it rather than tear down the session.
                return
            if in_flight.callback is not None:
                in_flight.callback()
            return
        if packet.packet_type == PACKET_SUBACK:
            # MQTT 3.1.1 §3.9.3: granted_qos 0x80 means the broker rejected
            # the filter; surface it as a protocol error.
            if packet.granted_qos and 0x80 in packet.granted_qos:
                # Evict before faulting so self-heal doesn't re-issue the rejected filter.
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
            # Fire and clear the one-shot on_subscribe (slot 1 of the desired-set
            # entry) so self-heal replays stay callback-silent.
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
        self._discard_pending(_AWAIT_CONNACK, packet_id=None)
        if packet.return_code != 0:
            # Rejection reasons (MQTT 3.1.1 §3.2.2.3); inline so the dict allocates only on rejection.
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
            if packet.return_code in _PERMANENT_CONNACK_CODES:
                self._permanent_failure = True
            self.state = ProtocolState.FAILED
            return
        self.state = ProtocolState.CONNECTED
        self._self_heal_attempts = 0
        self._self_heal_retry_at_ticks = None
        self._next_ping_due_ticks = self._deadline(self._ping_interval_ms, now_ms=now_ms)
        # Replay subscriptions unless the broker resumed our session
        # (clean_session=False and session_present=1), where they still live.
        if self._clean_session or not packet.session_present:
            self._replay_subscriptions()
        # Drain buffered publishes before on_connect, so they precede any it issues.
        self._drain_pre_connect_queue()
        self.on_connect()

    def _replay_subscriptions(self):
        if not self._subscriptions:
            return
        for topic, entry in self._subscriptions.items():
            qos = entry[0]
            packet_id = self._allocate_packet_id()
            packet = encode_subscribe(
                packet_id=packet_id, subscriptions=[(topic, qos)],
            )
            # Route through headroom, not the user cap: a full user queue would
            # fault into a reconnect-replay loop that never reconnects.
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
        # A SUBACK carries only the id, so find the topic via the pending entry.
        for pending in self._pending_responses:
            if pending.awaiting == _AWAIT_SUBACK and pending.packet_id == packet_id:
                if pending.topic is not None:
                    self._subscriptions.pop(pending.topic, None)
                return

    def _discard_pending(self, awaiting, *, packet_id, callback_arg=None):
        # Remove the matching PendingResponse and fire its callback; returns it or None.
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

    def _check_deadlines(self, now_ms):
        # Neither loop copies its collection: every path that mutates it
        # returns immediately, so the iterator never sees the change.
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
            # DUP flag is bit 3 of byte 0 (MQTT 3.1.1 §4.3.2); identical every
            # retry, so build it once and reuse.
            if entry.dup_packet_bytes is None:
                dup_packet = bytearray(entry.packet_bytes)
                dup_packet[0] |= 0x08
                entry.dup_packet_bytes = bytes(dup_packet)
            # Headroom full: leave the deadline so it retries next tick without burning a retry.
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

        if self._send_deadline_ticks is not None:
            if self._ticks.ticks_diff(self._send_deadline_ticks, now_ms) <= 0:
                self.last_error = MQTTError(
                    "send timeout: tx queue made no progress for "
                    f"{self._send_timeout_ms} ms",
                )
                self.state = ProtocolState.FAILED
                return

    def _check_keepalive(self, now_ms):
        if not self._keepalive_enabled:
            return
        if self.state != ProtocolState.CONNECTED:
            return
        if self._ticks.ticks_diff(self._next_ping_due_ticks, now_ms) > 0:
            return
        # Don't double-send while a PINGRESP is already pending.
        for pending in self._pending_responses:
            if pending.awaiting == _AWAIT_PINGRESP:
                return
        if not self._enqueue_internal_tx(PACKET_PINGREQ):
            return
        self._pending_responses.append(
            PendingResponse(
                awaiting=_AWAIT_PINGRESP,
                deadline_ticks=self._deadline(self._ack_timeout_ms, now_ms=now_ms),
            ),
        )
        self._next_ping_due_ticks = self._deadline(self._ping_interval_ms, now_ms=now_ms)

    def _deadline(self, offset_ms, *, now_ms=None):
        # Pass now_ms inside the tick loop so deadlines share one ticks_ms() reading.
        if now_ms is None:
            now_ms = self._ticks.ticks_ms()
        return self._ticks.ticks_add(now_ms, offset_ms)
