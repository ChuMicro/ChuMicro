"""``MQTTClient`` holds one connection to an MQTT broker and moves messages through it one step at a time.

This module also defines the ``ProtocolState`` names, the ``InboundPublish``
message record, the ``WhenOversized`` policy names, and
``default_client_id()``.
"""

import errno
from collections import deque

from chumicro_mqtt._wire import (
    DEFAULT_RX_BUFFER_SIZE,
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
    """Names for the states ``MQTTClient.state`` moves through, each a plain string.

    Attributes:
        DISCONNECTED: Before the first ``connect()``, and after
            ``disconnect()``.
        AWAITING_TRANSPORT: Opening the network connection: DNS lookup, TCP
            connect, and TLS handshake.  A client built on a ready socket
            skips this state.
        CONNECTING: Connection open, waiting for the broker's CONNACK reply
            to the client's CONNECT packet.
        CONNECTED: The broker accepted the connection.  Messages flow.
        FAILED: The connection dropped or the broker refused it.
            ``last_error`` holds the cause.  A client with a
            ``transport_factory`` reconnects from here unless the refusal
            was final.
    """

    DISCONNECTED = "disconnected"
    AWAITING_TRANSPORT = "awaiting_transport"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"


class InboundPublish:
    """One message from the broker, as ``MQTTClient.next_message()`` returns it.

    Attributes:
        topic: Topic the message was published to, as a ``str``.
        payload: Message body as ``bytes``.
    """

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
    """Record ``MQTTClient`` keeps for each sent QoS 1 message until the broker's PUBACK confirms it.

    The client resends ``packet_bytes`` with the DUP flag set each time
    ``deadline_ticks`` passes, up to ``publish_retry_max`` times.
    """

    def __init__(self, packet_id, packet_bytes, deadline_ticks, callback=None):
        self.packet_id = packet_id
        self.packet_bytes = packet_bytes
        self.retry_count = 0
        self.deadline_ticks = deadline_ticks
        self.callback = callback
        self.dup_packet_bytes = None


class PendingResponse:
    """Record ``MQTTClient`` keeps for each broker reply it waits on: CONNACK, SUBACK, UNSUBACK, or PINGRESP.

    The client moves to ``FAILED`` when the reply misses ``deadline_ticks``.
    """

    def __init__(self, awaiting, deadline_ticks, packet_id=None, callback=None, topic=None):
        self.awaiting = awaiting
        self.deadline_ticks = deadline_ticks
        self.packet_id = packet_id
        self.callback = callback
        self.topic = topic


class WhenOversized:
    """Values for ``when_oversized``: what ``MQTTClient`` does with a message too big for ``rx_buffer_size``.

    The whole PUBLISH packet counts against ``rx_buffer_size``: header,
    topic, and payload.  The client reads an oversized message off the socket
    in buffer-sized pieces and throws the pieces away, so the board never
    allocates memory for the full message.  Both drop policies still send the
    PUBACK for a QoS 1 message, so the broker stops resending it.

    Attributes:
        DROP_SILENT: Drop the message and stay connected.
        DROP_WITH_EVENT: Drop the message, call
            ``on_oversized(reported_length, topic)``, and stay connected.
            The default.
        DISCONNECT: Treat the message as a protocol error.  The client moves
            to ``FAILED`` with an ``MQTTProtocolError`` in ``last_error``.
    """

    DROP_SILENT = "drop_silent"

    DROP_WITH_EVENT = "drop_with_event"

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
    """Return an MQTT client id built from this board's chip id, as ``"<prefix>-<chip id in hex>"``.

    A broker identifies each session by its client id, so every board needs
    its own.  This id differs between boards and stays the same across
    reboots, which lets a broker resume the board's session after a power
    cycle.  The chip id comes from ``microcontroller.cpu.uid`` on
    CircuitPython, ``machine.unique_id()`` on MicroPython, and the network
    card's MAC address (``uuid.getnode()``) on CPython.  When none of those
    lookups works, the function returns ``"<prefix>-mqtt"``.  Two boards with
    that same fallback id disconnect each other from the broker.
    ``default_client_id("greenhouse")`` returns a string such as
    ``"greenhouse-e8db84a1b2c3"``.
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
    """Connects to an MQTT broker, then publishes and receives messages without blocking the main loop.

    ``connect()`` starts the connection and returns at once.  The main loop
    then calls ``check(now_ms)`` and ``handle(now_ms)`` on every pass, where
    ``now_ms`` comes from ``chumicro_timing.ticks_ms()``.  Each ``handle()``
    call does one bounded step of network work.  A ``chumicro_runner.Runner``
    makes both calls itself after ``runner.add(client)``.  ``publish()``,
    ``subscribe()``, and ``unsubscribe()`` work in every state.
    ``from_config()`` builds a client that reconnects by itself after a drop.

    Every ``on_*`` callback below starts as a function that does nothing.
    The client calls them from inside ``handle()``.  ``disconnect()`` calls
    ``on_disconnect`` too.

    Attributes:
        state: The current ``ProtocolState`` value.
        last_error: The ``MQTTError`` behind the most recent failure, or
            ``None``.
        on_message: Called as ``on_message(topic, payload)`` for each message
            on a subscribed topic, with ``topic`` a ``str`` and ``payload``
            ``bytes``.  It stops firing once ``next_message()`` is called.
        on_connect: Called as ``on_connect()`` each time the broker accepts
            the connection, reconnects included.
        on_disconnect: Called as ``on_disconnect()`` when ``disconnect()``
            runs and when an accepted connection drops.  A failed reconnect
            attempt stays silent.
        on_publish: Called as ``on_publish(topic, payload)`` for every
            message this client publishes, at the same moment as the
            ``on_publish`` argument of ``publish()``.
        on_subscribe: Called as ``on_subscribe(topic, granted_qos)`` when the
            broker first confirms a ``subscribe()``.
        on_unsubscribe: Called as ``on_unsubscribe(topic)`` when the broker
            confirms an ``unsubscribe()``.
        on_oversized: Called as ``on_oversized(reported_length, topic)`` when
            a message bigger than ``rx_buffer_size`` is dropped under
            ``WhenOversized.DROP_WITH_EVENT``.  ``reported_length`` is the
            size in bytes the packet announced for its topic, packet id, and
            payload together.  ``topic`` is ``None`` when the topic itself did
            not fit in the buffer.
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
        **constructor_kwargs: object,
    ) -> "MQTTClient":
        """Build a client from a flat config mapping, with a transport that reconnects after a drop.

        With neither ``socket`` nor ``transport_factory`` given, the client
        dials ``mqtt.broker.host`` and ``mqtt.broker.port`` through
        ``chumicro_sockets.sockets_factory`` and dials again after every drop.
        The client reads these keys:

        - ``mqtt.broker.host`` and ``mqtt.broker.port``: the broker's
          address, required unless ``socket`` or ``transport_factory`` is
          given.
        - ``mqtt.client_id``: defaults to ``default_client_id()``.
        - ``mqtt.keep_alive_seconds``: defaults to ``60``.
        - ``mqtt.username`` and ``mqtt.password``: default to ``None``.
        - ``mqtt.when_disconnected``: defaults to ``"queue"``.

        Args:
            config: A ``dict`` or other mapping with ``get()``, ``in``, and
                ``[]``.
            radio: The CircuitPython radio, such as ``wifi.radio``.
                MicroPython and CPython ignore it.
            ssl_context: TLS settings for the broker connection.  Passing one
                turns TLS on.
            socket: Connected socket to use instead of dialing the config's
                broker address.
            transport_factory: Connector factory to use instead of dialing
                the config's broker address.
            ticks: Clock object, passed to the constructor.
            **constructor_kwargs: Any other constructor argument.  A keyword
                given here wins over the config value.

        Returns:
            A new ``MQTTClient`` in the ``DISCONNECTED`` state.

        Raises:
            ValueError: ``config`` has no ``get()`` method.
            MissingConfigKey: ``mqtt.broker.host`` or ``mqtt.broker.port``
                is missing.
            RuntimeError: Neither ``socket`` nor ``transport_factory`` was
                given, and ``chumicro_sockets.sockets_factory`` is missing
                from the board.
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
        kwargs = {
            "socket": socket,
            "transport_factory": transport_factory,
            "client_id": config.get("mqtt.client_id") or default_client_id(),
            "keep_alive_seconds": config.get("mqtt.keep_alive_seconds", 60),
            "username": config.get("mqtt.username"),
            "password": config.get("mqtt.password"),
            "when_disconnected": config.get("mqtt.when_disconnected", "queue"),
            "ticks": ticks,
        }
        kwargs.update(constructor_kwargs)
        return cls(**kwargs)

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
        when_oversized: str = WhenOversized.DROP_WITH_EVENT,
        when_disconnected: str = "queue",
        pre_connect_queue_size: int = 8,
        recv_budget_per_tick: int = 1024,
        max_tx_queue_size: int = 20,
        send_timeout_seconds: float | None = None,
        ticks: object | None = None,
    ) -> None:
        """Build a client in the ``DISCONNECTED`` state.  Network traffic starts at ``connect()``.

        Args:
            socket: Connected TCP or TLS socket to the broker, with
                ``recv_into()``, ``send()``, and ``close()``.  The client sets
                it non-blocking.  Pass ``socket``, ``transport_factory``, or
                both.  With both, the client starts on ``socket`` and uses
                the factory to reconnect.
            transport_factory: Zero-argument callable that returns a new
                connector, an object that opens the connection over several
                ``tick(now_ms)`` calls, such as ``chumicro_sockets.connector``.
                The client calls it at ``connect()`` when it has no socket,
                and again for every reconnect.
            client_id: Name the broker knows this client by.  Each client on
                a broker needs its own, and ``default_client_id()`` builds
                one.
            keep_alive_seconds: Keep-alive interval in seconds, sent to the
                broker on connect.  The broker drops a client that stays
                silent for one and a half intervals, so the client sends a
                PINGREQ packet, the MQTT keep-alive ping, every half
                interval, at least 1 s apart.
                ``0`` turns keep-alive off.
            ack_timeout_seconds: Seconds the client waits for each broker
                reply, and for the network connection to open.  A late PUBACK
                makes the client resend the message.  Any other late reply
                moves the client to ``FAILED``.
            publish_retry_max: How many times the client resends an
                unconfirmed QoS 1 message before it moves to ``FAILED``.
            username: User name the broker checks, or ``None``.
            password: Password the broker checks, or ``None``.
            clean_session: ``True`` asks the broker for a fresh session on
                every connect.  ``False`` asks it to keep this client's
                subscriptions and undelivered QoS 1 messages across
                reconnects.  With ``False`` the client also keeps its own
                unconfirmed QoS 1 messages to resend.
            will_topic: Topic of the last will, or ``None`` for no will.
                ``set_will()`` explains the last will and changes it later.
            will_message: Payload of the last will.
            will_qos: QoS level of the last will, 0 or 1.
            will_retain: ``True`` makes the last will the topic's retained
                message.
            rx_buffer_size: Size in bytes of the receive buffer, allocated
                once.  ``None`` selects 256.  An incoming message whose packet
                is bigger is dropped under ``when_oversized``.
            when_oversized: A ``WhenOversized`` value.
            when_disconnected: What ``publish()`` does before the client is
                ``CONNECTED``.  ``"queue"`` holds the message in the
                pre-connect queue, which goes out, oldest first, once the
                broker accepts the connection.  ``"raise"`` raises
                ``MQTTError``.
            pre_connect_queue_size: How many messages the pre-connect queue
                holds.
            recv_budget_per_tick: Most bytes one ``handle()`` call reads from
                the socket.
            max_tx_queue_size: Most packets ``publish()``, ``subscribe()``,
                and ``unsubscribe()`` can leave waiting to be sent.  The next
                call raises ``MQTTBackpressureError``.
            send_timeout_seconds: Seconds the send queue may sit with no
                bytes written before the client moves to ``FAILED``.
                ``None`` uses ``ack_timeout_seconds``.
            ticks: Clock object with ``ticks_ms()``, ``ticks_add()``, and
                ``ticks_diff()``.  ``None`` selects ``chumicro_timing.ticks``.

        Raises:
            ValueError: Neither ``socket`` nor ``transport_factory`` was
                given, or ``when_disconnected`` is not ``"queue"`` or
                ``"raise"``.
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

        self._rx_buffer_size = (
            rx_buffer_size if rx_buffer_size is not None else DEFAULT_RX_BUFFER_SIZE
        )
        self._decoder = PacketDecoder(rx_buffer_size=self._rx_buffer_size)

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
        """Start connecting to the broker and return at once.

        Later ``handle()`` calls open the network connection, send the
        CONNECT packet, and wait for the broker's CONNACK reply.
        ``on_connect`` fires when the broker accepts.  ``connect()`` is safe
        in every state.  In ``DISCONNECTED`` it starts a connection.  In
        ``FAILED`` it clears ``hold()`` and any final refusal.  A client with
        a ``transport_factory`` then retries on the next ``handle()`` without
        waiting out the backoff.  While connecting or connected it does
        nothing.
        """
        self._reconnect_held = False
        self._user_wants_connected = True
        if self.state == ProtocolState.DISCONNECTED:
            self._permanent_failure = False
            self._self_heal_attempts = 0
            self._self_heal_retry_at_ticks = None
            if self._socket is None:
                if not self._start_transport():
                    self._enter_failed()
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
        """Pause automatic reconnects until the next ``connect()``.

        A held client in ``FAILED`` stays there, keeps ``last_error``, and
        makes no reconnect attempts.  ``publish()`` still queues.  A program
        calls ``hold()`` when it knows the network link is down, and
        ``connect()`` when the link returns.
        """
        self._reconnect_held = True

    def _start_transport(self, now_ms=None):
        # Build the connector and enter AWAITING_TRANSPORT; False on factory error.
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
        return True

    def _enqueue_connect_packet(self, now_ms=None):
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
        self._await_ack(_AWAIT_CONNACK, now_ms=now_ms)

    def disconnect(self):
        """Close the connection to the broker and move to ``DISCONNECTED``.

        A connecting or connected client first writes the DISCONNECT packet
        straight to the socket, which tells the broker to discard the last
        will.  Packets still waiting to be sent and messages in the
        pre-connect queue are dropped.  The subscriptions stay.  The next
        ``connect()`` sends them again.  ``on_disconnect`` fires.
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
        self._decoder = PacketDecoder(rx_buffer_size=self._rx_buffer_size)

    def set_will(
        self,
        topic: str | None,
        message: bytes | None = None,
        *,
        qos: int = 0,
        retain: bool = False,
    ):
        """Set the last will, a message the broker publishes if this client drops without ``disconnect()``.

        The will travels in the CONNECT packet, so a change takes effect at
        the next connect or reconnect.  A power cut, a wifi loss, or a crash
        triggers the will.  A clean ``disconnect()`` cancels it.

        Args:
            topic: Topic the broker publishes the will to.  ``None`` turns
                the will off.
            message: Will payload as ``bytes``.  ``None`` sends an empty
                payload.
            qos: QoS level of the will, 0 or 1.
            retain: ``True`` makes the will the topic's retained message.

        Raises:
            UnsupportedQoSError: ``qos`` is 2 or higher.
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
        """Queue a message to ``topic`` and return at once.

        A connected client adds the PUBLISH packet to its send queue.  Later
        ``handle()`` calls write the queue out.  Before ``CONNECTED``, the
        default ``when_disconnected="queue"`` holds the message in the
        pre-connect queue until the broker accepts the connection.

        QoS 0 sends the message once and gets no confirmation.  QoS 1
        resends the message, up to ``publish_retry_max`` times, until the
        broker confirms it with a PUBACK packet, so the message can arrive
        twice.

        Args:
            topic: Topic name, such as ``"home/kitchen/temp"``, sent as
                written.
            payload: Message body.  A ``str`` is encoded as UTF-8.
            qos: 0 or 1.
            retain: ``True`` asks the broker to keep this message as the
                topic's retained message and hand it to every later
                subscriber.
            on_publish: Called as ``on_publish(topic, payload)`` once this
                message is done, with ``payload`` as ``bytes``.  A QoS 1
                message is done when the broker's PUBACK arrives.  A QoS 0
                message is done once its bytes are written to the socket.

        Raises:
            UnsupportedQoSError: ``qos`` is 2 or higher.
            MQTTBackpressureError: The send queue or the pre-connect queue is
                full.
            MQTTError: The client is not ``CONNECTED`` and was built with
                ``when_disconnected="raise"``.
        """
        if qos > 1:
            raise UnsupportedQoSError(
                "qos must be 0 or 1; QoS 2 is reserved-not-implemented",
            )
        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = bytes(payload)

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

    def _drain_pre_connect_queue(self, now_ms=None):
        queue = self._pre_connect_queue
        while queue:
            topic, payload_bytes, qos, retain, on_publish = queue.popleft()
            self._do_publish(
                topic, payload_bytes, qos, retain, on_publish, now_ms=now_ms,
            )

    def _do_publish(self, topic, payload_bytes, qos, retain, on_publish,
                    now_ms=None):
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
            deadline_ticks=self._deadline(self._ack_timeout_ms, now_ms=now_ms),
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
        """Add ``topic`` to the subscriptions, so its messages reach ``on_message`` or ``next_message()``.

        ``subscribe()`` works in every state.  A connected client sends the
        SUBSCRIBE packet now.  Any other client sends it once the broker
        accepts the connection.  The client sends every subscription again
        after each reconnect, unless the broker resumed a
        ``clean_session=False`` session that still holds them.  A filter the
        broker refuses sends the client to ``FAILED`` with an
        ``MQTTProtocolError``.  The client then drops that filter from its
        subscriptions.

        Args:
            topic: Topic filter.  ``+`` matches one level and ``#`` matches
                every level below, as in ``"home/+/temp"`` or ``"home/#"``.
            qos: Highest QoS level the broker should deliver at, 0 or 1.
            on_subscribe: Called once as ``on_subscribe(topic, granted_qos)``
                when the broker first confirms this subscription.
                ``granted_qos`` is the list of granted levels from the
                broker's SUBACK reply, such as ``[1]``.

        Raises:
            MQTTBackpressureError: The client is connected and its send queue
                is full.  The subscriptions stay unchanged.
            UnsupportedQoSError: ``qos`` is 2 or higher, in any state.  The
                subscriptions stay unchanged.
        """
        if qos > 1:
            raise UnsupportedQoSError(
                "subscribe qos must be 0 or 1; QoS 2 is reserved-not-implemented",
            )

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
            self._await_ack(_AWAIT_SUBACK, packet_id=packet_id, topic=topic)
        self._subscriptions[topic] = [qos, _wrapped]

    def unsubscribe(self, topic, *, on_unsubscribe=None):
        """Remove ``topic`` from the client's subscriptions.

        ``unsubscribe()`` works in every state.  A connected client also
        sends an UNSUBSCRIBE packet to the broker.  Any other client only
        forgets the filter, so the next connect leaves it out.  ``topic`` is
        the filter string passed to ``subscribe()``.  The optional
        ``on_unsubscribe`` is called as ``on_unsubscribe(topic)`` when the
        broker confirms with its UNSUBACK reply.

        Raises:
            MQTTBackpressureError: The client is connected and its send queue
                is full.  The subscriptions stay unchanged.
        """
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

        self._await_ack(_AWAIT_UNSUBACK, packet_id=packet_id, callback=_wrapped)

    def next_message(self):
        """Wait in a generator task for the next message: ``message = yield from client.next_message()``.

        A generator task is a function with ``yield`` in it that
        ``chumicro_runner.Runner.add_generator()`` runs one step per tick.
        The first call switches delivery from ``on_message`` to a queue of up
        to 16 messages.  A full queue drops its oldest message.

        The ``yield from`` expression evaluates to the next
        ``InboundPublish``, or to ``None`` once the client has stopped for
        good.  The client stops for good after ``disconnect()``, after a
        refusal that retrying cannot fix, and after a drop on a client with
        no ``transport_factory``.
        """
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
        """Return ``True`` when the client has work for ``handle()`` on this pass of the loop.

        ``check()`` returns ``False`` in ``DISCONNECTED``, and in ``FAILED``
        after ``hold()`` or after a refusal that retrying cannot fix.  The
        client ignores ``now_ms`` and accepts it to match the runner's calling
        convention.
        """
        if self.state == ProtocolState.FAILED and (
            self._permanent_failure or self._reconnect_held
        ):
            return False
        return self.state != ProtocolState.DISCONNECTED

    @property
    def io_socket(self):
        """Socket ``Runner.wait()`` watches for this client, or ``None`` when there is none to watch.

        While the network connection opens, it is the connector's socket.
        In ``DISCONNECTED`` and ``FAILED`` it is ``None``.
        """
        if self.state == ProtocolState.AWAITING_TRANSPORT:
            return self._connector.io_socket if self._connector is not None else None
        if self._socket is None:
            return None
        if self.state in (ProtocolState.DISCONNECTED, ProtocolState.FAILED):
            return None
        return self._socket

    def io_interest(self, now_ms):
        """Return the socket events ``Runner.wait()`` should wake for, as a bitmask.

        Bit value 1 asks to wake when ``io_socket`` is readable, and 2 when
        it is writable.  The client asks to read while connecting or
        connected, and to write while packets wait in its send queue.  ``0``
        asks for neither.  ``now_ms`` is the current ``ticks_ms()`` reading.
        """
        if self.state == ProtocolState.AWAITING_TRANSPORT:
            if self._connector is None:
                return 0
            connector_interest = self._connector.io_interest(now_ms)
            return connector_interest & (_IO_READ | _IO_WRITE)
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
        """Fail the connection after ``Runner.wait()`` sees an error or hang-up on ``io_socket``.

        ``eventmask`` holds the poll event bits the runner saw, such as
        ``POLLERR`` or ``POLLHUP``.  The client moves to ``FAILED`` with an
        ``MQTTError`` naming ``eventmask`` in ``last_error``.  A client with
        a ``transport_factory`` then reconnects as after any drop.  The
        client ignores ``now_ms``.
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
        self._enter_failed()

    def next_deadline(self, now_ms):
        """Return the ``ticks_ms()`` value by which ``handle()`` must run, or ``None`` with no timer set.

        ``Runner.wait()`` wakes no later than this tick, even when the socket
        stays quiet.  The client reports the nearest of its keep-alive ping,
        reply deadlines, QoS 1 resends, send timeout, and reconnect time.
        ``now_ms`` is the current ``ticks_ms()`` reading.
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
            if self._self_heal_active():
                if self._self_heal_retry_at_ticks is None:
                    return now_ms
                return self._self_heal_retry_at_ticks
            return None
        if self.state == ProtocolState.DISCONNECTED:
            return None
        ticks_diff = self._ticks.ticks_diff
        nearest = None
        # With keepalive disabled the ping due-tick is never re-armed, so
        # reporting it would pin next_deadline in the past and busy-spin wait().
        if self.state == ProtocolState.CONNECTED and self._keepalive_enabled:
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
        """Do one bounded step of network work, whenever ``check()`` returns ``True``.

        One call advances the connection attempt, checks reply deadlines and
        resends late QoS 1 messages, sends a keep-alive ping when one is due,
        reads up to ``recv_budget_per_tick`` bytes, dispatches the packets
        those bytes complete, and sends one queued packet.  Callbacks run
        inside this call.  The DNS lookup and the TLS handshake each run to
        completion inside one call, which holds up the loop until they
        finish.

        An MQTT or socket error moves the client to ``FAILED`` and lands in
        ``last_error`` instead of raising.  Any other exception a callback
        raises propagates out of ``handle()``.  In ``FAILED``, a client with a
        ``transport_factory`` reconnects, waiting 1 s before the second
        attempt and doubling the wait after each failure up to 60 s.
        ``now_ms`` is the current ``ticks_ms()`` reading that every deadline
        is measured against.
        """
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
            self._enter_failed()
        except OSError as error:
            self.last_error = MQTTError(f"socket error: {error}")
            self._enter_failed()

    def _enter_failed(self):
        # State settles before the callback fires, so a reentrant
        # connect() / hold() / disconnect() from inside on_disconnect
        # sees FAILED rather than the dying state.  Connect attempts
        # that never established (CONNECTING / AWAITING_TRANSPORT, the
        # self-heal retry cycle) stay silent: on_disconnect reports the
        # end of an established session, mirroring on_connect.
        was_connected = self.state == ProtocolState.CONNECTED
        self.state = ProtocolState.FAILED
        if was_connected:
            self.on_disconnect()

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
        self._enter_failed()
        return True

    def _advance_connector(self, now_ms):
        connector = self._connector
        connector.tick(now_ms)
        if connector.state == "ready":
            self._socket = connector.socket
            self._connector = None
            self._transport_deadline_ticks = None
            _force_non_blocking(self._socket)
            self._enqueue_connect_packet(now_ms=now_ms)
            self.state = ProtocolState.CONNECTING
            return True
        if connector.state == "failed":
            self.last_error = MQTTError(
                f"connector failed: {connector.last_error}",
            )
            self._connector = None
            self._transport_deadline_ticks = None
            self._enter_failed()
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
                _AWAIT_UNSUBACK, packet_id=packet.packet_id,
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
            self._enter_failed()
            return
        self.state = ProtocolState.CONNECTED
        self._self_heal_attempts = 0
        self._self_heal_retry_at_ticks = None
        self._next_ping_due_ticks = self._deadline(self._ping_interval_ms, now_ms=now_ms)
        # Replay subscriptions unless the broker resumed our session
        # (clean_session=False and session_present=1), where they still live.
        if self._clean_session or not packet.session_present:
            self._replay_subscriptions(now_ms=now_ms)
        # Drain buffered publishes before on_connect, so they precede any it issues.
        self._drain_pre_connect_queue(now_ms=now_ms)
        self.on_connect()

    def _replay_subscriptions(self, now_ms=None):
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
            self._await_ack(
                _AWAIT_SUBACK, packet_id=packet_id, topic=topic, now_ms=now_ms,
            )

    def _evict_rejected_subscription(self, packet_id):
        # A SUBACK carries only the id, so find the topic via the pending entry.
        for pending in self._pending_responses:
            if pending.awaiting == _AWAIT_SUBACK and pending.packet_id == packet_id:
                if pending.topic is not None:
                    self._subscriptions.pop(pending.topic, None)
                return

    def _discard_pending(self, awaiting, *, packet_id):
        # Remove the matching PendingResponse and fire its callback; returns it or None.
        for index, pending in enumerate(self._pending_responses):
            if pending.awaiting != awaiting:
                continue
            if packet_id is not None and pending.packet_id != packet_id:
                continue
            self._pending_responses.pop(index)
            if pending.callback is not None:
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
                self._enter_failed()
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
            self._enter_failed()
            return

        if self._send_deadline_ticks is not None:
            if self._ticks.ticks_diff(self._send_deadline_ticks, now_ms) <= 0:
                self.last_error = MQTTError(
                    "send timeout: tx queue made no progress for "
                    f"{self._send_timeout_ms} ms",
                )
                self._enter_failed()
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
            # The tx queue is at its hard cap, so outbound traffic is already
            # flowing and the broker sees activity; retry a full interval out
            # rather than leaving the due-tick in the past, which would
            # busy-spin wait() until the queue drains.
            self._next_ping_due_ticks = self._deadline(
                self._ping_interval_ms, now_ms=now_ms,
            )
            return
        self._await_ack(_AWAIT_PINGRESP, now_ms=now_ms)
        self._next_ping_due_ticks = self._deadline(self._ping_interval_ms, now_ms=now_ms)

    def _deadline(self, offset_ms, *, now_ms=None):
        # Pass now_ms inside the tick loop so deadlines share one ticks_ms() reading.
        if now_ms is None:
            now_ms = self._ticks.ticks_ms()
        return self._ticks.ticks_add(now_ms, offset_ms)

    def _await_ack(self, awaiting, *, packet_id=None, callback=None,
                   topic=None, now_ms=None):
        # Arm a PendingResponse with the shared ack timeout.
        self._pending_responses.append(
            PendingResponse(
                awaiting=awaiting,
                deadline_ticks=self._deadline(self._ack_timeout_ms, now_ms=now_ms),
                packet_id=packet_id,
                callback=callback,
                topic=topic,
            ),
        )
