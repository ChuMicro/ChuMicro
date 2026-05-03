"""MQTT 3.1.1 wire format: exceptions, constants, codecs, encoders, decoder.

Consolidates what used to be ``_errors.py`` + ``_packets.py`` +
``_encoder.py`` + ``_decoder.py`` into one module.  The pieces are
intertwined (every encoder needs the constants and the codec, every
decoder needs the constants and the protocol exceptions) and shipping
them as four files cost ~16 KB of FAT cluster waste on Pi Pico W.
"""

import struct

try:
    from micropython import const
except ImportError:
    def const(value):
        return value


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MQTTError(Exception):
    """Base class for every chumicro-mqtt failure."""


class MQTTProtocolError(MQTTError):
    """The broker sent something the spec doesn't allow.

    Always a peer or network bug — the right response is usually
    disconnect + reconnect.
    """


class MQTTConnectError(MQTTError):
    """CONNACK arrived with a non-zero return code.

    The numeric ``return_code`` is on the exception so callers can branch.
    """

    def __init__(self, message, *, return_code):
        super().__init__(message)
        self.return_code = return_code


class MQTTBackpressureError(MQTTError):
    """The outbound queue is full; caller must back off.

    Raised by :meth:`MQTTClient.publish` (and friends) when appending
    another packet would exceed ``max_tx_queue_size``.  The client
    is otherwise unaffected — drain by calling :meth:`MQTTClient.handle`
    once and retry the publish.
    """


class UnsupportedQoSError(MQTTError):
    """User requested QoS 2.  Constants are reserved; handlers aren't wired."""


# ---------------------------------------------------------------------------
# Packet types — first byte of the fixed header (with flags zero'd)
# ---------------------------------------------------------------------------

PACKET_CONNECT = const(0x10)
PACKET_CONNACK = const(0x20)
PACKET_PUBLISH = const(0x30)
PACKET_PUBACK = const(0x40)
PACKET_SUBSCRIBE = const(0x82)
PACKET_SUBACK = const(0x90)
PACKET_UNSUBSCRIBE = const(0xA2)
PACKET_UNSUBACK = const(0xB0)
PACKET_PINGRESP = const(0xD0)

#: Pre-encoded PINGREQ (no payload, two bytes total).
PACKET_PINGREQ = b"\xc0\x00"

#: Pre-encoded DISCONNECT (no payload, two bytes total).
PACKET_DISCONNECT = b"\xe0\x00"

# Reserved for QoS 2 (not implemented; constants kept so future work
# can wire handlers without an audit pass).
PACKET_PUBREC = const(0x50)
PACKET_PUBREL = const(0x62)
PACKET_PUBCOMP = const(0x70)


# ---------------------------------------------------------------------------
# Codec helpers
# ---------------------------------------------------------------------------


def encode_varlen(value):
    """Encode *value* as an MQTT variable-length integer (1-4 bytes).

    7 bits per byte, little-endian, bit 7 = continuation flag.
    Raises :class:`ValueError` above the spec maximum (268_435_455).
    """
    if value < 0 or value > 268_435_455:
        raise ValueError(f"varlen value {value} out of MQTT range")
    output = bytearray()
    while True:
        digit = value & 0x7F
        value >>= 7
        if value > 0:
            digit |= 0x80
        output.append(digit)
        if value == 0:
            return output


def decode_varlen(buffer, start_index):
    """Decode an MQTT variable-length integer from *buffer*.

    Returns ``(value, bytes_consumed)``.  Returns ``(0, 0)`` when the
    buffer doesn't yet contain a complete varlen at *start_index* —
    the caller should pull more bytes and retry.
    """
    value = 0
    shift = 0
    for consumed in range(4):  # MQTT 3.1.1 caps varlen at 4 bytes
        offset = start_index + consumed
        if offset >= len(buffer):
            return 0, 0
        digit = buffer[offset]
        value |= (digit & 0x7F) << shift
        shift += 7
        if (digit & 0x80) == 0:
            return value, consumed + 1
    return 0, 0


def encode_string(value):
    """Encode *value* as ``2-byte big-endian length || UTF-8 bytes``.

    *value* may be ``str`` (auto-encoded) or already-encoded bytes.
    """
    if isinstance(value, str):
        value = value.encode("utf-8")
    return struct.pack(">H", len(value)) + value


def topic_matches(topic, pattern):
    """Return ``True`` when *topic* matches the wildcard *pattern*.

    ``+`` matches one topic level; ``#`` matches any number of levels
    and must be the last character of the pattern.
    """
    topic_levels = topic.split("/")
    pattern_levels = pattern.split("/")

    for index, pattern_level in enumerate(pattern_levels):
        if pattern_level == "#":
            return index == len(pattern_levels) - 1
        if pattern_level == "+":
            if index >= len(topic_levels):
                return False
            continue
        if index >= len(topic_levels) or pattern_level != topic_levels[index]:
            return False

    return len(pattern_levels) == len(topic_levels)


# ---------------------------------------------------------------------------
# Packet encoders
# ---------------------------------------------------------------------------

#: MQTT 3.1.1 protocol-name + level prefix used in every CONNECT.
#:   2 bytes  0x00 0x04   length of "MQTT"
#:   4 bytes  "MQTT"
#:   1 byte   0x04        protocol level (4 == 3.1.1)
_CONNECT_PROTOCOL_PREFIX = b"\x00\x04MQTT\x04"


def encode_connect(
    *,
    client_id,
    keep_alive_seconds,
    clean_session=True,
    username=None,
    password=None,
    will_topic=None,
    will_message=None,
    will_qos=0,
    will_retain=False,
):
    """Build a CONNECT packet ready to send.

    Args:
        client_id: Identifier the broker uses to track this session.
        keep_alive_seconds: Seconds the broker waits between PINGs
            before disconnecting.  PINGREQ runs at half this interval
            client-side.
        clean_session: ``False`` resumes persistent broker state for
            QoS 1+ retransmission across reconnects.
        username / password: Optional auth credentials.
        will_topic / will_message: Last-will message broker publishes
            on uncleanly-dropped connection.
        will_qos / will_retain: QoS + retain flags for the will message.

    Raises:
        UnsupportedQoSError: ``will_qos > 1``.
    """
    if will_qos > 1:
        raise UnsupportedQoSError(
            "will_qos must be 0 or 1; QoS 2 is reserved-not-implemented",
        )

    flags = 0
    if clean_session:
        flags |= 0x02
    if will_topic is not None:
        flags |= 0x04
        flags |= (will_qos & 0x03) << 3
        if will_retain:
            flags |= 0x20
    if username is not None:
        flags |= 0x80
    if password is not None:
        flags |= 0x40

    variable_header = bytearray(_CONNECT_PROTOCOL_PREFIX)
    variable_header.append(flags)
    variable_header.extend(struct.pack(">H", keep_alive_seconds))

    payload = bytearray(encode_string(client_id))
    if will_topic is not None:
        payload.extend(encode_string(will_topic))
        payload.extend(encode_string(will_message if will_message is not None else b""))
    if username is not None:
        payload.extend(encode_string(username))
    if password is not None:
        payload.extend(encode_string(password))

    remaining = bytes(variable_header) + bytes(payload)
    return bytes(bytearray((PACKET_CONNECT,)) + encode_varlen(len(remaining))) + remaining


def encode_publish(*, topic, payload, qos=0, retain=False, packet_id=None):
    """Build a PUBLISH packet ready to send.

    *payload* is sent verbatim; ``str`` is auto-encoded as UTF-8.

    Raises:
        UnsupportedQoSError: ``qos > 1``.
        ValueError: ``qos > 0`` without a *packet_id*.
    """
    if qos > 1:
        raise UnsupportedQoSError(
            "qos must be 0 or 1; QoS 2 is reserved-not-implemented",
        )
    if qos > 0 and packet_id is None:
        raise ValueError(
            "QoS > 0 requires a packet_id (allocate via InFlightTable.allocate_id)",
        )

    if isinstance(payload, str):
        payload = payload.encode("utf-8")

    # First byte: 0x30 | (qos << 1) | retain | (dup_flag << 3 — always 0 here).
    fixed_byte_one = PACKET_PUBLISH | (qos << 1)
    if retain:
        fixed_byte_one |= 0x01

    variable_header = bytearray(encode_string(topic))
    if qos > 0:
        variable_header.extend(struct.pack(">H", packet_id))

    remaining = bytes(variable_header) + bytes(payload)
    return bytes(bytearray((fixed_byte_one,)) + encode_varlen(len(remaining))) + remaining


def encode_subscribe(*, packet_id, subscriptions):
    """Build a SUBSCRIBE packet for one-or-more ``(topic, qos)`` pairs.

    Raises:
        ValueError: Empty *subscriptions* — a SUBSCRIBE with zero
            filters is a protocol error.
        UnsupportedQoSError: Any *qos > 1*.
    """
    pairs = list(subscriptions)
    if not pairs:
        raise ValueError("SUBSCRIBE requires at least one (topic, qos) pair")
    for _topic, qos in pairs:
        if qos > 1:
            raise UnsupportedQoSError(
                "subscription qos must be 0 or 1; QoS 2 is reserved-not-implemented",
            )

    variable_header = bytearray(struct.pack(">H", packet_id))
    payload = bytearray()
    for topic, qos in pairs:
        payload.extend(encode_string(topic))
        payload.append(qos & 0x03)

    remaining = bytes(variable_header) + bytes(payload)
    # SUBSCRIBE first byte is 0x82 — the 0x02 low-nibble is required by spec.
    return bytes(bytearray((PACKET_SUBSCRIBE,)) + encode_varlen(len(remaining))) + remaining


def encode_unsubscribe(*, packet_id, topics):
    """Build an UNSUBSCRIBE packet for one-or-more topics.

    Raises:
        ValueError: Empty *topics*.
    """
    pairs = list(topics)
    if not pairs:
        raise ValueError("UNSUBSCRIBE requires at least one topic")

    variable_header = bytearray(struct.pack(">H", packet_id))
    payload = bytearray()
    for topic in pairs:
        payload.extend(encode_string(topic))

    remaining = bytes(variable_header) + bytes(payload)
    return bytes(bytearray((PACKET_UNSUBSCRIBE,)) + encode_varlen(len(remaining))) + remaining


def encode_puback(*, packet_id):
    """Build a PUBACK packet acknowledging a received QoS 1 PUBLISH."""
    # PUBACK fixed header is always 0x40 0x02 followed by the 2-byte packet-id.
    return bytes((0x40, 0x02)) + struct.pack(">H", packet_id)


# ---------------------------------------------------------------------------
# Inbound-packet parser
# ---------------------------------------------------------------------------

#: Default pre-allocated steady-state buffer size (bytes).
DEFAULT_RX_BUFFER_SIZE = 256

#: Default cap on a single inbound message.  Anything bigger triggers
#: the user-configured ``WhenOversized`` policy.
DEFAULT_MAX_MESSAGE_SIZE = 256 * 1024


class ParsedPublish:
    """Inbound PUBLISH parsed off the wire."""

    __slots__ = ("packet_id", "payload", "qos", "retain", "topic")

    def __init__(self, *, topic, payload, qos, retain, packet_id):
        self.topic = topic
        self.payload = payload
        self.qos = qos
        self.retain = retain
        self.packet_id = packet_id


class ParsedAck:
    """Inbound CONNACK / PUBACK / SUBACK / UNSUBACK / PINGRESP.

    A single shape covers all five.  ``return_code`` is set only on
    CONNACK; ``granted_qos`` only on SUBACK; ``packet_id`` is None
    for CONNACK / PINGRESP.
    """

    __slots__ = ("granted_qos", "packet_id", "packet_type", "return_code")

    def __init__(
        self,
        *,
        packet_type,
        packet_id=None,
        return_code=None,
        granted_qos=None,
    ):
        self.packet_type = packet_type
        self.packet_id = packet_id
        self.return_code = return_code
        self.granted_qos = granted_qos


class _OversizedMessage:
    """Signal that the next message exceeds ``max_message_size``.

    Carries topic + reported length so DROP_WITH_EVENT can fire
    ``on_oversized(topic, reported_length)`` after the payload is
    discarded.
    """

    __slots__ = ("packet_id", "qos", "reported_length", "topic")

    def __init__(self, *, topic, reported_length, qos, packet_id):
        self.topic = topic
        self.reported_length = reported_length
        self.qos = qos
        self.packet_id = packet_id


class PacketDecoder:
    """Incremental MQTT packet parser with a pre-allocated RX buffer.

    Two-buffer pattern: the steady-state buffer is reused tick-after-
    tick; oversized messages allocate a one-shot "degraded" buffer of
    the right size + drain into it.

    Usage::

        decoder = PacketDecoder()
        # Each tick:
        nbytes = sock.recv_into(decoder.fill_buffer(), decoder.fill_capacity())
        decoder.advance(nbytes)
        while True:
            packet = decoder.read_next()
            if packet is None:
                break
            handle(packet)  # ParsedPublish / ParsedAck / _OversizedMessage
    """

    def __init__(
        self,
        *,
        rx_buffer_size=DEFAULT_RX_BUFFER_SIZE,
        max_message_size=DEFAULT_MAX_MESSAGE_SIZE,
    ):
        self._buffer = bytearray(rx_buffer_size)
        # Cached memoryview into ``_buffer`` — the steady-state buffer
        # is allocated once and never resized, so the view is stable
        # for the parser's lifetime.  Cached to avoid constructing a
        # fresh memoryview on every ``fill_buffer``/``read_next`` call
        # (per-packet hot path on a busy MQTT subscriber).
        self._buffer_view = memoryview(self._buffer)
        self._buffer_size = rx_buffer_size
        self._buffer_length = 0
        self._max_message_size = max_message_size
        # Degraded path: one-shot buffer for oversize messages whose
        # bodies don't fit in the steady-state buffer.  Drained to
        # recover sync, then released.  ``_degraded_view`` mirrors the
        # cached-view pattern when the path activates.
        self._degraded_buffer = None
        self._degraded_view = None
        self._degraded_total = 0
        self._degraded_consumed = 0
        self._degraded_topic = None
        self._degraded_qos = 0
        self._degraded_packet_id = None

    def fill_buffer(self):
        """Return the bytearray slice the next ``recv_into`` should write into."""
        if self._degraded_buffer is not None:
            return self._degraded_view[self._degraded_consumed:]
        return self._buffer_view[self._buffer_length:]

    def fill_capacity(self):
        """Bytes the parser is willing to receive on the next ``recv_into``."""
        if self._degraded_buffer is not None:
            return self._degraded_total - self._degraded_consumed
        return self._buffer_size - self._buffer_length

    def advance(self, nbytes):
        """Tell the parser *nbytes* were just written into the fill region."""
        if nbytes <= 0:
            return
        if self._degraded_buffer is not None:
            self._degraded_consumed += nbytes
        else:
            self._buffer_length += nbytes

    def read_next(self):
        """Return the next complete packet, or ``None`` if more bytes needed.

        Returns one of: :class:`ParsedPublish`, :class:`ParsedAck`,
        :class:`_OversizedMessage`, or ``None``.  Raises
        :class:`MQTTProtocolError` on malformed input.
        """
        if self._degraded_buffer is not None:
            return self._maybe_finish_degraded()

        if self._buffer_length == 0:
            return None

        # Need at least the fixed header byte + first remaining-length byte.
        if self._buffer_length < 2:
            return None

        # Use the cached view rather than constructing a fresh one
        # per call.  ``_buffer`` is allocated once at construction
        # and never resized, so the view is stable for the parser's
        # lifetime.
        view = self._buffer_view
        fixed_byte = view[0]
        message_length, varlen_consumed = decode_varlen(view, 1)
        if varlen_consumed == 0:
            return None  # Incomplete varlen — wait for more bytes.
        header_length = 1 + varlen_consumed
        total_length = header_length + message_length

        if total_length > self._buffer_size:
            return self._enter_oversized_path(fixed_byte, message_length, view, header_length)

        if self._buffer_length < total_length:
            return None  # Body still in transit.

        body_start = header_length
        body_end = total_length
        packet = self._parse_packet(fixed_byte, view, body_start, body_end)

        # Drain the consumed packet from the buffer (memmove the rest).
        leftover = self._buffer_length - total_length
        if leftover > 0:
            self._buffer[:leftover] = self._buffer[total_length:self._buffer_length]
        self._buffer_length = leftover
        return packet

    def _parse_packet(self, fixed_byte, view, body_start, body_end):
        packet_type = fixed_byte & 0xF0
        if packet_type == PACKET_PUBLISH:
            return self._parse_publish(fixed_byte, view, body_start, body_end)
        if packet_type == PACKET_CONNACK:
            return self._parse_connack(view, body_start, body_end)
        if packet_type == PACKET_PUBACK:
            return self._parse_simple_ack(PACKET_PUBACK, view, body_start, body_end)
        if packet_type == PACKET_SUBACK:
            return self._parse_suback(view, body_start, body_end)
        if packet_type == PACKET_UNSUBACK:
            return self._parse_simple_ack(PACKET_UNSUBACK, view, body_start, body_end)
        if packet_type == PACKET_PINGRESP:
            return ParsedAck(packet_type=PACKET_PINGRESP)
        raise MQTTProtocolError(
            f"unknown packet type 0x{packet_type:02X} from broker",
        )

    def _parse_publish(self, fixed_byte, view, body_start, body_end):
        # qos bits are bits 1-2 of the fixed-header byte; retain is bit 0.
        qos = (fixed_byte >> 1) & 0x03
        retain = bool(fixed_byte & 0x01)
        # ``struct.unpack`` accepts memoryview directly — no ``bytes()``
        # wrap needed, which would otherwise copy 2 bytes per integer
        # field (4-6 wasted allocs per PUBLISH).
        topic_length = struct.unpack(">H", view[body_start:body_start + 2])[0]
        topic_start = body_start + 2
        topic_end = topic_start + topic_length
        if topic_end > body_end:
            raise MQTTProtocolError("PUBLISH topic length exceeds remaining bytes")
        # ``bytes(view[a:b]).decode()`` stays — memoryview lacks decode().
        topic = bytes(view[topic_start:topic_end]).decode("utf-8")
        cursor = topic_end
        packet_id = None
        if qos > 0:
            if cursor + 2 > body_end:
                raise MQTTProtocolError(
                    "QoS > 0 PUBLISH missing 2-byte packet identifier",
                )
            packet_id = struct.unpack(">H", view[cursor:cursor + 2])[0]
            cursor += 2
        # Payload is returned to the caller as ``bytes`` (immutable +
        # decoupled from the parser's reusable buffer); one copy.
        payload = bytes(view[cursor:body_end])
        return ParsedPublish(
            topic=topic,
            payload=payload,
            qos=qos,
            retain=retain,
            packet_id=packet_id,
        )

    def _parse_connack(self, view, body_start, body_end):
        if body_end - body_start != 2:
            raise MQTTProtocolError("CONNACK body must be exactly 2 bytes")
        # First byte = ack flags (we only check session-present bit on resume).
        return_code = view[body_start + 1]
        return ParsedAck(packet_type=PACKET_CONNACK, return_code=return_code)

    def _parse_simple_ack(self, packet_type, view, body_start, body_end):
        if body_end - body_start != 2:
            raise MQTTProtocolError(
                f"packet type 0x{packet_type:02X} body must be 2 bytes",
            )
        packet_id = struct.unpack(">H", view[body_start:body_start + 2])[0]
        return ParsedAck(packet_type=packet_type, packet_id=packet_id)

    def _parse_suback(self, view, body_start, body_end):
        body_length = body_end - body_start
        if body_length < 3:
            raise MQTTProtocolError("SUBACK body must be at least 3 bytes")
        packet_id = struct.unpack(">H", view[body_start:body_start + 2])[0]
        granted_qos = list(view[body_start + 2:body_end])
        return ParsedAck(
            packet_type=PACKET_SUBACK,
            packet_id=packet_id,
            granted_qos=granted_qos,
        )

    def _enter_oversized_path(self, fixed_byte, message_length, view, header_length):
        """Switch to degraded-buffer mode for a too-big message.

        For a PUBLISH, the topic + optional packet-id likely fits in
        the steady-state buffer; the payload doesn't.  We pull what we
        have, parse the topic, then read-and-discard the rest to
        recover sync.  Non-PUBLISH oversize is a protocol error.
        """
        packet_type = fixed_byte & 0xF0
        if packet_type != PACKET_PUBLISH:
            raise MQTTProtocolError(
                f"oversized non-PUBLISH packet (type 0x{packet_type:02X}, "
                f"remaining length {message_length})",
            )
        body_start = header_length
        if self._buffer_length < body_start + 2:
            return None  # Need a few more bytes before we can parse the topic.
        # Use the cached ``_buffer_view`` (zero-copy slice) and skip the
        # ``bytes()`` wrap on struct.unpack args — memoryview is a
        # bytes-like object that struct accepts directly.
        view = self._buffer_view
        topic_length = struct.unpack(">H", view[body_start:body_start + 2])[0]
        topic_start = body_start + 2
        topic_end = topic_start + topic_length
        qos = (fixed_byte >> 1) & 0x03
        packet_id_bytes = 2 if qos > 0 else 0
        prelude_total = topic_end + packet_id_bytes
        if self._buffer_length < prelude_total:
            return None  # Need a few more bytes before we can parse the prelude.
        topic = bytes(view[topic_start:topic_end]).decode("utf-8")
        packet_id = None
        if qos > 0:
            packet_id = struct.unpack(">H", view[topic_end:topic_end + 2])[0]
        payload_remaining = (
            (header_length + message_length) - prelude_total
        )
        body_already_in_steady = self._buffer_length - prelude_total
        payload_to_drain = payload_remaining - body_already_in_steady
        if payload_to_drain <= 0:
            # Whole oversized message already in the steady-state buffer
            # (extreme corner case where buffer is huge but
            # max_message_size is even larger).  Emit immediately.
            self._buffer_length = 0
            return _OversizedMessage(
                topic=topic,
                reported_length=message_length,
                qos=qos,
                packet_id=packet_id,
            )
        # Normal path: drain into a degraded buffer.  Cache its view
        # so ``fill_buffer`` doesn't construct a fresh one per recv.
        self._degraded_buffer = bytearray(payload_to_drain)
        self._degraded_view = memoryview(self._degraded_buffer)
        self._degraded_total = payload_to_drain
        self._degraded_consumed = 0
        self._degraded_topic = topic
        self._degraded_qos = qos
        self._degraded_packet_id = packet_id
        # Reset steady-state buffer — we've extracted everything we need.
        self._buffer_length = 0
        return None  # Caller drains via fill_buffer()/advance() until full.

    def _maybe_finish_degraded(self):
        if self._degraded_consumed < self._degraded_total:
            return None
        event = _OversizedMessage(
            topic=self._degraded_topic,
            reported_length=self._degraded_total,
            qos=self._degraded_qos,
            packet_id=self._degraded_packet_id,
        )
        self._degraded_buffer = None
        self._degraded_view = None
        self._degraded_total = 0
        self._degraded_consumed = 0
        self._degraded_topic = None
        self._degraded_qos = 0
        self._degraded_packet_id = None
        return event
