"""MQTT 3.1.1 wire format: exceptions, packet-type constants, codecs,
encoders, and the incremental packet decoder.
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
    """The broker sent something the spec doesn't allow."""


class MQTTConnectError(MQTTError):
    """CONNACK arrived with a non-zero return code.

    The numeric ``return_code`` attribute lets callers branch on the
    rejection reason.
    """

    def __init__(self, message, *, return_code):
        super().__init__(message)
        self.return_code = return_code


class MQTTBackpressureError(MQTTError):
    """The outbound queue is full, so the caller must back off.

    Raised by :meth:`MQTTClient.publish` when another packet would exceed
    ``max_tx_queue_size``. Call :meth:`MQTTClient.handle` once to drain,
    then retry the publish.
    """


class UnsupportedQoSError(MQTTError):
    """User requested QoS 2, which is not implemented."""


# ---------------------------------------------------------------------------
# Packet-type bytes used as the first byte of the fixed header.  Most
# carry zeroed flag bits in the low nibble.  PACKET_SUBSCRIBE (0x82)
# and PACKET_UNSUBSCRIBE (0xA2) require 0x02 in the low nibble per spec.
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


# ---------------------------------------------------------------------------
# Codec helpers
# ---------------------------------------------------------------------------


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
        limit: One past the last readable byte, bounding the scan to the
            live write end so it never reads stale bytes past what was
            actually received. Defaults to ``len(buffer)``.

    Returns:
        ``(value, bytes_consumed)``, or ``(0, 0)`` when *buffer* does not
        yet hold a complete varlen at *start_index* (pull more bytes and
        retry).

    Raises:
        MQTTProtocolError: The varlen runs past 4 bytes (malformed, not
            merely incomplete).
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
    """Encode *value* as ``2-byte big-endian length || UTF-8 bytes``.

    *value* may be ``str`` (auto-encoded) or already-encoded bytes.
    """
    if isinstance(value, str):
        value = value.encode("utf-8")
    return struct.pack(">H", len(value)) + value


# Append-into helpers for the encoders: pack_into a pre-extended buffer
# instead of struct.pack, avoiding a bytes allocation per pack.
_ZERO2 = b"\x00\x00"


def _append_packed_h(buffer, value):
    """Append *value* to *buffer* as a big-endian 2-byte unsigned int."""
    buffer.extend(_ZERO2)
    struct.pack_into(">H", buffer, len(buffer) - 2, value)


def _append_string(buffer, value):
    """Append MQTT-encoded string (``2-byte length || utf-8 bytes``) to *buffer*."""
    if isinstance(value, str):
        value = value.encode("utf-8")
    _append_packed_h(buffer, len(value))
    buffer.extend(value)


def topic_matches(topic, pattern):
    """Return ``True`` when *topic* matches the wildcard *pattern*.

    ``+`` matches one topic level.  ``#`` matches any number of levels
    and must be the last character of the pattern.
    """
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


# ---------------------------------------------------------------------------
# Packet encoders
# ---------------------------------------------------------------------------

#: MQTT 3.1.1 protocol-name + level prefix used in every CONNECT.
#:   2 bytes  0x00 0x04   length of "MQTT"
#:   4 bytes  "MQTT"
#:   1 byte   0x04        protocol level (4 == 3.1.1)
_CONNECT_PROTOCOL_PREFIX = b"\x00\x04MQTT\x04"


def _finalize_packet(packet_type, remaining):
    """Prepend the MQTT fixed header to the variable header + payload bytes."""
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
        keep_alive_seconds: Seconds the broker waits between PINGs
            before disconnecting.  PINGREQ runs at half this interval
            client-side.
        clean_session: ``False`` resumes persistent broker state for
            QoS 1+ retransmission across reconnects.
        username: Optional auth username (paired with *password*).
        password: Optional auth password.
        will_topic: Topic for the broker's last-will message.  Published
            on uncleanly-dropped connection.  ``None`` disables the will.
        will_message: Payload for the broker's last-will message.
        will_qos: QoS for the will message (0 or 1).
        will_retain: ``True`` retains the will message on the broker.

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

    *payload* is sent verbatim.  ``str`` is auto-encoded as UTF-8.

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

    # First byte: 0x30 | (qos << 1) | retain | (dup_flag << 3, always 0 here).
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
        ValueError: Empty *subscriptions*.  A SUBSCRIBE with zero
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

    body = bytearray()
    _append_packed_h(body, packet_id)
    for topic, qos in pairs:
        _append_string(body, topic)
        body.append(qos & 0x03)

    # SUBSCRIBE first byte is 0x82.  The 0x02 low-nibble is required by spec.
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


#: Fixed 2-byte PUBACK header: ``PACKET_PUBACK`` followed by remaining-length 2.
_PUBACK_FIXED_HEADER = bytes((PACKET_PUBACK, 2))


def encode_puback(*, packet_id):
    """Build a PUBACK packet acknowledging a received QoS 1 PUBLISH."""
    output = bytearray(_PUBACK_FIXED_HEADER)
    _append_packed_h(output, packet_id)
    return bytes(output)


# ---------------------------------------------------------------------------
# Inbound-packet parser
# ---------------------------------------------------------------------------

#: Default size (bytes) of the pre-allocated steady-state RX buffer.
#: A PUBLISH whose total wire size exceeds this routes through the
#: oversized-discard tier (see :class:`PacketDecoder`).
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
    """Inbound CONNACK / PUBACK / SUBACK / UNSUBACK / PINGRESP.

    A single shape covers all five.  ``return_code`` and
    ``session_present`` are set only on CONNACK.  ``granted_qos`` is set
    only on SUBACK.  ``packet_id`` is None for CONNACK / PINGRESP.
    """

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
    """An inbound PUBLISH that exceeded ``rx_buffer_size``; payload discarded."""

    def __init__(self, *, topic, reported_length, qos, packet_id):
        self.topic = topic
        self.reported_length = reported_length
        self.qos = qos
        self.packet_id = packet_id


# Drain modes for ``PacketDecoder._drain_mode``.  See the class
# docstring below for the tier model.
_DRAIN_NONE = const(0)
_DRAIN_OVERSIZED = const(1)


class PacketDecoder:
    """Incremental MQTT packet parser with a two-tier inbound size model.

    Tier 1 (steady): a packet that fits ``rx_buffer_size`` parses inline
    from the pre-allocated buffer with no allocation. Size ``rx_buffer_size``
    up to cover the largest PUBLISH a consumer must receive intact.

    Tier 2 (oversized): a packet larger than ``rx_buffer_size`` cannot be
    kept. Its payload drains through the steady buffer in passes and the
    decoder emits an :class:`_OversizedMessage` with the payload gone, so
    heap cost stays constant no matter how large the inbound message is.

    Usage::

        decoder = PacketDecoder(rx_buffer_size=256)
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
    ):
        self._buffer = bytearray(rx_buffer_size)
        # Cache the view once: the buffer is never resized, so this avoids
        # rebuilding a memoryview on every fill/read (a per-packet hot path).
        self._buffer_view = memoryview(self._buffer)
        self._buffer_size = rx_buffer_size
        # Read-cursor pattern: _buffer_length is the write end, _read_offset
        # the consume start. See _consume/_compact for the compaction rule.
        self._buffer_length = 0
        self._read_offset = 0
        # Drain state for an inbound PUBLISH that overflowed rx_buffer_size
        # (see the class tier model).
        self._drain_mode = _DRAIN_NONE
        self._drain_remaining = 0          # oversized bytes still to consume from the socket
        self._drain_topic = None
        self._drain_qos = 0
        self._drain_packet_id = None
        self._drain_message_length = 0     # MQTT remaining-length, reported back on oversize

    def fill_buffer(self):
        """Return the bytearray slice the next ``recv_into`` should write into.

        Oversized mode reuses this buffer as a rolling sink (write, count,
        discard); steady mode appends at the write cursor.
        """
        return self._buffer_view[self._buffer_length:]

    def fill_capacity(self):
        """Bytes the parser is willing to receive on the next ``recv_into``."""
        if self._drain_mode == _DRAIN_OVERSIZED:
            # Cap each pass at the smaller of remaining-to-drain and buffer
            # space; advance() resets the buffer when it fills.
            available = self._buffer_size - self._buffer_length
            return min(self._drain_remaining, available)
        return self._buffer_size - self._buffer_length

    def advance(self, nbytes):
        """Tell the parser *nbytes* were just written into the fill region."""
        if nbytes <= 0:
            return
        if self._drain_mode == _DRAIN_OVERSIZED:
            self._drain_remaining -= nbytes
            # Discarded bytes: reset the rolling sink for the next pass.
            self._buffer_length = 0
            return
        self._buffer_length += nbytes

    def read_next(self):
        """Return the next complete packet, or ``None`` if more bytes needed.

        Returns one of: :class:`ParsedPublish`, :class:`ParsedAck`,
        :class:`_OversizedMessage`, or ``None``.  Raises
        :class:`MQTTProtocolError` on malformed input.
        """
        if self._drain_mode == _DRAIN_OVERSIZED:
            return self._maybe_finish_oversized()

        base = self._read_offset
        live = self._buffer_length - base
        # Need at least the fixed header byte + first remaining-length byte.
        if live < 2:
            return None

        view = self._buffer_view
        fixed_byte = view[base]
        # Bound the varlen scan to the live write end so it never reads
        # stale bytes left past _buffer_length by an earlier compaction.
        message_length, varlen_consumed = decode_varlen(
            view, base + 1, self._buffer_length,
        )
        if varlen_consumed == 0:
            return None  # Incomplete varlen: wait for more bytes.
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
            # Body still in transit. If the buffer is full and the packet
            # fits but not past the cursor, compact now to reopen fill space,
            # else fill_capacity() stays 0 and recv is never called again.
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
        # qos bits are bits 1-2 of the fixed-header byte.  retain is bit 0.
        qos = (fixed_byte >> 1) & 0x03
        retain = bool(fixed_byte & 0x01)
        # A PUBLISH shorter than its 2-byte topic-length prefix is malformed;
        # this check raises MQTTProtocolError instead of a raw struct error.
        if body_end - body_start < 2:
            raise MQTTProtocolError("PUBLISH missing 2-byte topic-length prefix")
        # struct.unpack takes a memoryview directly, sparing a bytes() copy.
        topic_length = struct.unpack(">H", view[body_start:body_start + 2])[0]
        topic_start = body_start + 2
        topic_end = topic_start + topic_length
        if topic_end > body_end:
            raise MQTTProtocolError("PUBLISH topic length exceeds remaining bytes")
        # 3-arg str() decodes the memoryview directly, sparing a bytes() copy.
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
        # Copy to bytes so the payload is decoupled from the reusable buffer.
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
        # Byte 0 flags: bit 0 is session-present (MQTT 3.1.1 §3.2.2.1), which
        # the client uses to skip subscription replay. Byte 1 is the return code.
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
        # Oversized PUBLISH: can't parse inline, so drain the payload with no
        # payload-sized allocation. Parse the topic prelude for the diagnostic
        # _OversizedMessage when it fits; otherwise emit it with topic=None.
        # A non-PUBLISH this large is a protocol error.
        packet_type = fixed_byte & 0xF0
        if packet_type != PACKET_PUBLISH:
            raise MQTTProtocolError(
                f"oversized non-PUBLISH packet (type 0x{packet_type:02X}, "
                f"remaining length {message_length})",
            )
        live = self._buffer_length - base
        if live < header_length + 2:
            return None  # Need 2 more bytes for the topic-length field.

        view = self._buffer_view
        body_start = base + header_length
        topic_length = struct.unpack(">H", view[body_start:body_start + 2])[0]
        qos = (fixed_byte >> 1) & 0x03
        packet_id_bytes = 2 if qos > 0 else 0
        prelude_length = header_length + 2 + topic_length + packet_id_bytes

        if prelude_length > self._buffer_size:
            # Oversize topic: it doesn't fit the buffer, so we can't parse it
            # or the packet_id after it. Drain the rest and emit topic=None;
            # buffered header/partial-topic bytes are discarded too.
            self._enter_oversized_drain(
                bytes_still_on_wire=total_length - live,
                topic=None,
                qos=qos,
                packet_id=None,
                message_length=message_length,
            )
            return self._maybe_finish_oversized()

        if live < prelude_length:
            return None  # Need more bytes before the prelude is complete.

        topic_start = body_start + 2
        topic_end = topic_start + topic_length
        topic = str(view[topic_start:topic_end], "utf-8")
        packet_id = None
        if qos > 0:
            packet_id = struct.unpack(">H", view[topic_end:topic_end + 2])[0]

        # Discard the payload via rolling drain, no payload-sized allocation.
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
        # Discard the buffer: prelude already parsed, payload bytes aren't kept.
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
