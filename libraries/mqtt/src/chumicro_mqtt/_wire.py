"""MQTT 3.1.1 wire format: exceptions, constants, codecs, encoders, and the packet decoder."""

import struct

try:
    from micropython import const
except ImportError:
    def const(value):
        return value


class MQTTError(Exception):
    """Base class for every chumicro-mqtt failure."""


class MQTTProtocolError(MQTTError):
    """The broker sent something the spec doesn't allow."""


class MQTTConnectError(MQTTError):
    """CONNACK arrived with a non-zero return code."""

    def __init__(self, message, *, return_code):
        super().__init__(message)
        self.return_code = return_code


class MQTTBackpressureError(MQTTError):
    """The outbound queue is full, so the caller must back off."""


class UnsupportedQoSError(MQTTError):
    """User requested QoS 2, which is not implemented."""


# PACKET_SUBSCRIBE (0x82) and PACKET_UNSUBSCRIBE (0xA2) carry 0x02 in the low
# nibble, required by spec; the other packet types zero it.
PACKET_CONNECT = const(0x10)
PACKET_CONNACK = const(0x20)
PACKET_PUBLISH = const(0x30)
PACKET_PUBACK = const(0x40)
PACKET_SUBSCRIBE = const(0x82)
PACKET_SUBACK = const(0x90)
PACKET_UNSUBSCRIBE = const(0xA2)
PACKET_UNSUBACK = const(0xB0)
PACKET_PINGRESP = const(0xD0)

#: Pre-encoded PINGREQ packet.
PACKET_PINGREQ = b"\xc0\x00"

#: Pre-encoded DISCONNECT packet.
PACKET_DISCONNECT = b"\xe0\x00"


def encode_varlen(value):
    """Encode *value* as an MQTT variable-length integer (1-4 bytes).

    Raises:
        ValueError: *value* is negative or above the spec maximum
            (268_435_455).
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


def decode_varlen(buffer, start_index, limit=None):
    """Decode an MQTT variable-length integer from *buffer*.

    Args:
        buffer: Bytes to read from.
        start_index: Offset of the first varlen byte.
        limit: One past the last readable byte; defaults to ``len(buffer)``.

    Returns:
        ``(value, bytes_consumed)``, or ``(0, 0)`` when no complete varlen is present yet.

    Raises:
        MQTTProtocolError: The varlen runs past 4 bytes.
    """
    if limit is None:
        limit = len(buffer)
    value = 0
    shift = 0
    for consumed in range(4):  # MQTT 3.1.1 caps varlen at 4 bytes
        offset = start_index + consumed
        if offset >= limit:
            return 0, 0
        digit = buffer[offset]
        value |= (digit & 0x7F) << shift
        shift += 7
        if (digit & 0x80) == 0:
            return value, consumed + 1
    raise MQTTProtocolError("varlen exceeds 4 bytes (malformed)")


def encode_string(value):
    """Encode *value* as ``2-byte big-endian length || UTF-8 bytes``."""
    if isinstance(value, str):
        value = value.encode("utf-8")
    return struct.pack(">H", len(value)) + value


_ZERO2 = b"\x00\x00"


def _append_packed_h(buffer, value):
    buffer.extend(_ZERO2)
    struct.pack_into(">H", buffer, len(buffer) - 2, value)


def _append_string(buffer, value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    _append_packed_h(buffer, len(value))
    buffer.extend(value)


def topic_matches(topic, pattern):
    """Return ``True`` when *topic* matches the wildcard *pattern*."""
    topic_levels = topic.split("/")
    pattern_levels = pattern.split("/")
    pattern_count = len(pattern_levels)
    topic_count = len(topic_levels)
    index = 0
    while index < pattern_count:
        pattern_level = pattern_levels[index]
        if pattern_level == "#":
            return index == pattern_count - 1
        if pattern_level == "+":
            if index >= topic_count:
                return False
        elif index >= topic_count or pattern_level != topic_levels[index]:
            return False
        index += 1
    return pattern_count == topic_count


# MQTT 3.1.1 CONNECT prefix: 2-byte length, "MQTT", protocol level 0x04.
_CONNECT_PROTOCOL_PREFIX = b"\x00\x04MQTT\x04"


def _finalize_packet(packet_type, remaining):
    return bytes(bytearray((packet_type,)) + encode_varlen(len(remaining))) + remaining


def encode_connect(
    *,
    client_id: str,
    keep_alive_seconds: int,
    clean_session: bool = True,
    username: str | None = None,
    password: str | None = None,
    will_topic: str | None = None,
    will_message: bytes | None = None,
    will_qos: int = 0,
    will_retain: bool = False,
) -> bytes:
    """Build a CONNECT packet ready to send.

    Args:
        client_id: Identifier the broker uses to track this session.
        keep_alive_seconds: Broker idle timeout; PINGREQ runs at half this interval.
        clean_session: ``False`` resumes persistent broker state across reconnects.
        username: Optional auth username.
        password: Optional auth password.
        will_topic: Last-will topic; ``None`` disables the will.
        will_message: Last-will payload.
        will_qos: Will QoS (0 or 1).
        will_retain: ``True`` retains the will on the broker.

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

    body = bytearray(_CONNECT_PROTOCOL_PREFIX)
    body.append(flags)
    _append_packed_h(body, keep_alive_seconds)
    _append_string(body, client_id)
    if will_topic is not None:
        _append_string(body, will_topic)
        _append_string(body, will_message if will_message is not None else b"")
    if username is not None:
        _append_string(body, username)
    if password is not None:
        _append_string(body, password)

    return _finalize_packet(PACKET_CONNECT, bytes(body))


def encode_publish(*, topic, payload, qos=0, retain=False, packet_id=None):
    """Build a PUBLISH packet ready to send.

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

    fixed_byte_one = PACKET_PUBLISH | (qos << 1)
    if retain:
        fixed_byte_one |= 0x01

    body = bytearray()
    _append_string(body, topic)
    if qos > 0:
        _append_packed_h(body, packet_id)
    body.extend(payload)

    return _finalize_packet(fixed_byte_one, bytes(body))


def encode_subscribe(*, packet_id, subscriptions):
    """Build a SUBSCRIBE packet for one-or-more ``(topic, qos)`` pairs.

    Raises:
        ValueError: Empty *subscriptions*.
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

    body = bytearray()
    _append_packed_h(body, packet_id)
    for topic, qos in pairs:
        _append_string(body, topic)
        body.append(qos & 0x03)

    return _finalize_packet(PACKET_SUBSCRIBE, bytes(body))


def encode_unsubscribe(*, packet_id, topics):
    """Build an UNSUBSCRIBE packet for one-or-more topics.

    Raises:
        ValueError: Empty *topics*.
    """
    pairs = list(topics)
    if not pairs:
        raise ValueError("UNSUBSCRIBE requires at least one topic")

    body = bytearray()
    _append_packed_h(body, packet_id)
    for topic in pairs:
        _append_string(body, topic)

    return _finalize_packet(PACKET_UNSUBSCRIBE, bytes(body))


_PUBACK_FIXED_HEADER = bytes((PACKET_PUBACK, 2))


def encode_puback(*, packet_id):
    """Build a PUBACK packet acknowledging a received QoS 1 PUBLISH."""
    output = bytearray(_PUBACK_FIXED_HEADER)
    _append_packed_h(output, packet_id)
    return bytes(output)


#: Default size (bytes) of the pre-allocated steady-state RX buffer.
DEFAULT_RX_BUFFER_SIZE = const(256)


class ParsedPublish:
    """Inbound PUBLISH parsed off the wire."""

    def __init__(self, *, topic, payload, qos, retain, packet_id):
        self.topic = topic
        self.payload = payload
        self.qos = qos
        self.retain = retain
        self.packet_id = packet_id


class ParsedAck:
    """Inbound CONNACK / PUBACK / SUBACK / UNSUBACK / PINGRESP."""

    def __init__(
        self,
        *,
        packet_type,
        packet_id=None,
        return_code=None,
        granted_qos=None,
        session_present=None,
    ):
        self.packet_type = packet_type
        self.packet_id = packet_id
        self.return_code = return_code
        self.granted_qos = granted_qos
        self.session_present = session_present


class _OversizedMessage:
    def __init__(self, *, topic, reported_length, qos, packet_id):
        self.topic = topic
        self.reported_length = reported_length
        self.qos = qos
        self.packet_id = packet_id


_DRAIN_NONE = const(0)
_DRAIN_OVERSIZED = const(1)


class PacketDecoder:
    """Incremental MQTT packet parser with a two-tier inbound size model."""

    def __init__(
        self,
        *,
        rx_buffer_size=DEFAULT_RX_BUFFER_SIZE,
    ):
        self._buffer = bytearray(rx_buffer_size)
        self._buffer_view = memoryview(self._buffer)
        self._buffer_size = rx_buffer_size
        self._buffer_length = 0
        self._read_offset = 0
        self._drain_mode = _DRAIN_NONE
        self._drain_remaining = 0
        self._drain_topic = None
        self._drain_qos = 0
        self._drain_packet_id = None
        self._drain_message_length = 0

    def fill_buffer(self):
        """Return the bytearray slice the next ``recv_into`` should write into."""
        return self._buffer_view[self._buffer_length:]

    def fill_capacity(self):
        """Bytes the parser is willing to receive on the next ``recv_into``."""
        if self._drain_mode == _DRAIN_OVERSIZED:
            available = self._buffer_size - self._buffer_length
            return min(self._drain_remaining, available)
        return self._buffer_size - self._buffer_length

    def advance(self, nbytes):
        """Tell the parser *nbytes* were just written into the fill region."""
        if nbytes <= 0:
            return
        if self._drain_mode == _DRAIN_OVERSIZED:
            self._drain_remaining -= nbytes
            self._buffer_length = 0
            return
        self._buffer_length += nbytes

    def read_next(self):
        """Return the next complete packet, or ``None`` if more bytes needed.

        Returns:
            :class:`ParsedPublish`, :class:`ParsedAck`, :class:`_OversizedMessage`, or ``None``.

        Raises:
            MQTTProtocolError: The input is malformed.
        """
        if self._drain_mode == _DRAIN_OVERSIZED:
            return self._maybe_finish_oversized()

        base = self._read_offset
        live = self._buffer_length - base
        # Need the type byte plus at least one remaining-length byte.
        if live < 2:
            return None

        view = self._buffer_view
        fixed_byte = view[base]
        message_length, varlen_consumed = decode_varlen(
            view, base + 1, self._buffer_length,
        )
        if varlen_consumed == 0:
            return None
        header_length = 1 + varlen_consumed
        total_length = header_length + message_length

        if total_length > self._buffer_size:
            return self._enter_drain_path(
                fixed_byte=fixed_byte,
                message_length=message_length,
                base=base,
                header_length=header_length,
                total_length=total_length,
            )

        if live < total_length:
            # Buffer full mid-packet: compact to reopen fill space, else
            # fill_capacity() stays 0 and recv is never called again.
            if self._buffer_length == self._buffer_size and self._read_offset > 0:
                self._compact()
            return None

        body_start = base + header_length
        body_end = base + total_length
        packet = self._parse_packet(fixed_byte, view, body_start, body_end)
        self._consume(total_length)
        return packet

    def _consume(self, count):
        self._read_offset += count
        # Compact only once the cursor passes halfway, amortizing the copy.
        if self._read_offset * 2 >= self._buffer_size:
            self._compact()

    def _compact(self):
        live = self._buffer_length - self._read_offset
        if live > 0:
            self._buffer_view[:live] = self._buffer_view[self._read_offset:self._buffer_length]
        self._buffer_length = live
        self._read_offset = 0

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
        # qos is bits 1-2 of the fixed-header byte, retain is bit 0.
        qos = (fixed_byte >> 1) & 0x03
        retain = bool(fixed_byte & 0x01)
        if body_end - body_start < 2:
            raise MQTTProtocolError("PUBLISH missing 2-byte topic-length prefix")
        topic_length = struct.unpack(">H", view[body_start:body_start + 2])[0]
        topic_start = body_start + 2
        topic_end = topic_start + topic_length
        if topic_end > body_end:
            raise MQTTProtocolError("PUBLISH topic length exceeds remaining bytes")
        topic = str(view[topic_start:topic_end], "utf-8")
        cursor = topic_end
        packet_id = None
        if qos > 0:
            if cursor + 2 > body_end:
                raise MQTTProtocolError(
                    "QoS > 0 PUBLISH missing 2-byte packet identifier",
                )
            packet_id = struct.unpack(">H", view[cursor:cursor + 2])[0]
            cursor += 2
        # Copy to bytes so the payload is decoupled from the reused buffer.
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
        # MQTT 3.1.1 §3.2.2: byte 0 bit 0 is session-present, byte 1 the return code.
        session_present = bool(view[body_start] & 0x01)
        return_code = view[body_start + 1]
        return ParsedAck(
            packet_type=PACKET_CONNACK,
            return_code=return_code,
            session_present=session_present,
        )

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

    def _enter_drain_path(self, *, fixed_byte, message_length, base, header_length, total_length):
        # Oversized PUBLISH: drain the payload with no payload-sized allocation.
        # A non-PUBLISH packet this large is a protocol error.
        packet_type = fixed_byte & 0xF0
        if packet_type != PACKET_PUBLISH:
            raise MQTTProtocolError(
                f"oversized non-PUBLISH packet (type 0x{packet_type:02X}, "
                f"remaining length {message_length})",
            )
        live = self._buffer_length - base
        if live < header_length + 2:
            return None

        view = self._buffer_view
        body_start = base + header_length
        topic_length = struct.unpack(">H", view[body_start:body_start + 2])[0]
        qos = (fixed_byte >> 1) & 0x03
        packet_id_bytes = 2 if qos > 0 else 0
        prelude_length = header_length + 2 + topic_length + packet_id_bytes

        if prelude_length > self._buffer_size:
            # Topic itself overflows the buffer: can't parse it or the
            # packet_id, so drain the rest and emit topic=None.
            self._enter_oversized_drain(
                bytes_still_on_wire=total_length - live,
                topic=None,
                qos=qos,
                packet_id=None,
                message_length=message_length,
            )
            return self._maybe_finish_oversized()

        if live < prelude_length:
            return None

        topic_start = body_start + 2
        topic_end = topic_start + topic_length
        topic = str(view[topic_start:topic_end], "utf-8")
        packet_id = None
        if qos > 0:
            packet_id = struct.unpack(">H", view[topic_end:topic_end + 2])[0]

        self._enter_oversized_drain(
            bytes_still_on_wire=total_length - live,
            topic=topic,
            qos=qos,
            packet_id=packet_id,
            message_length=message_length,
        )
        return self._maybe_finish_oversized()

    def _enter_oversized_drain(
        self, *, bytes_still_on_wire, topic, qos, packet_id, message_length,
    ):
        self._drain_remaining = max(0, bytes_still_on_wire)
        self._drain_topic = topic
        self._drain_qos = qos
        self._drain_packet_id = packet_id
        self._drain_message_length = message_length
        # Prelude parsed; discard the buffer so the payload drains as a sink.
        self._buffer_length = 0
        self._read_offset = 0
        self._drain_mode = _DRAIN_OVERSIZED

    def _maybe_finish_oversized(self):
        if self._drain_remaining > 0:
            return None
        event = _OversizedMessage(
            topic=self._drain_topic,
            reported_length=self._drain_message_length,
            qos=self._drain_qos,
            packet_id=self._drain_packet_id,
        )
        self._reset_drain_state()
        return event

    def _reset_drain_state(self):
        self._drain_mode = _DRAIN_NONE
        self._drain_remaining = 0
        self._drain_topic = None
        self._drain_qos = 0
        self._drain_packet_id = None
        self._drain_message_length = 0
