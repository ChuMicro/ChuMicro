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
# Packet types — first byte of the fixed header.  Most have flags zero'd;
# PACKET_SUBSCRIBE (0x82) and PACKET_UNSUBSCRIBE (0xA2) carry the
# spec-required 0x02 low-nibble flag bit.
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

    Returns ``(value, bytes_consumed)``.  Returns ``(0, 0)`` only when
    the buffer doesn't yet contain a complete varlen at *start_index*
    (incomplete — pull more bytes and retry).  A varlen still
    continuing past 4 bytes is malformed, not incomplete, so it raises
    :class:`MQTTProtocolError` rather than masquerading as "need more".
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
    raise MQTTProtocolError("varlen exceeds 4 bytes (malformed)")


def encode_string(value):
    """Encode *value* as ``2-byte big-endian length || UTF-8 bytes``.

    *value* may be ``str`` (auto-encoded) or already-encoded bytes.
    """
    if isinstance(value, str):
        value = value.encode("utf-8")
    return struct.pack(">H", len(value)) + value


# Internal append-via-pack_into helpers used by every encoder.  Cuts
# per-pack allocation in half on MicroPython (bench: 128 → 64 B/call
# on MP 1.26 unix-port) by extending the destination with a pre-built
# zero literal and writing directly with ``struct.pack_into`` instead
# of allocating a fresh ``bytes`` from ``struct.pack``.
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


def _topic_levels_match(topic_levels, pattern_levels):
    """Match pre-split topic / pattern level sequences.

    Internal hot-path helper for ``MQTTClient._handle_inbound_publish`` —
    the public :func:`topic_matches` splits both inputs every call; the
    client caches the pattern split at registration time and the topic
    split once per inbound message, then matches N stored patterns
    against the one cached split.
    """
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


def topic_matches(topic, pattern):
    """Return ``True`` when *topic* matches the wildcard *pattern*.

    ``+`` matches one topic level; ``#`` matches any number of levels
    and must be the last character of the pattern.
    """
    return _topic_levels_match(topic.split("/"), pattern.split("/"))


# ---------------------------------------------------------------------------
# Packet encoders
# ---------------------------------------------------------------------------

#: MQTT 3.1.1 protocol-name + level prefix used in every CONNECT.
#:   2 bytes  0x00 0x04   length of "MQTT"
#:   4 bytes  "MQTT"
#:   1 byte   0x04        protocol level (4 == 3.1.1)
_CONNECT_PROTOCOL_PREFIX = b"\x00\x04MQTT\x04"


def _finalize_packet(packet_type, remaining):
    """Wrap *remaining* with the MQTT fixed header.

    ``remaining`` is the variable-header + payload bytes.  Returns
    ``fixed_header || remaining`` as ``bytes``.  ``remaining`` is
    concatenated rather than slice-assigned into a pre-sized buffer,
    so the payload is copied exactly once even when it's large.
    """
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
        will_topic: Topic for the broker's last-will message — published
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

    body = bytearray()
    _append_string(body, topic)
    if qos > 0:
        _append_packed_h(body, packet_id)
    body.extend(payload)

    return _finalize_packet(fixed_byte_one, bytes(body))


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

    body = bytearray()
    _append_packed_h(body, packet_id)
    for topic, qos in pairs:
        _append_string(body, topic)
        body.append(qos & 0x03)

    # SUBSCRIBE first byte is 0x82 — the 0x02 low-nibble is required by spec.
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


#: Fixed 2-byte PUBACK header — always ``PACKET_PUBACK`` followed by remaining-length 2.
_PUBACK_FIXED_HEADER = bytes((PACKET_PUBACK, 2))


def encode_puback(*, packet_id):
    """Build a PUBACK packet acknowledging a received QoS 1 PUBLISH."""
    output = bytearray(_PUBACK_FIXED_HEADER)
    _append_packed_h(output, packet_id)
    return bytes(output)


# ---------------------------------------------------------------------------
# Inbound-packet parser
# ---------------------------------------------------------------------------

#: Default pre-allocated steady-state buffer size (bytes).  Inbound PUBLISHes
#: that fit within this size parse inline without any allocation; larger
#: messages either get a one-shot intact buffer (tier 2) or drain via
#: rolling discard (tier 3) — see :class:`PacketDecoder`.
DEFAULT_RX_BUFFER_SIZE = const(256)

#: Default cap on intact-delivery for a single inbound PUBLISH.  Messages
#: at or below this size are delivered to ``on_message`` with their full
#: payload (allocated one-shot, freed after delivery).  Above this size
#: the configured ``WhenOversized`` policy applies — payload is dropped
#: via rolling discard, no heap allocation beyond the steady-state buffer.
#: Default sized for typical embedded-board payloads on the 256 KB-RAM
#: minimum-tier board; raise for legitimately larger inbound messages.
DEFAULT_MAX_MESSAGE_BYTES = const(8 * 1024)


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

    A single shape covers all five.  ``return_code`` is set only on
    CONNACK; ``granted_qos`` only on SUBACK; ``packet_id`` is None
    for CONNACK / PINGRESP.
    """

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
    """Signal that an inbound PUBLISH exceeded ``max_message_bytes``.

    The payload itself is gone — the decoder drained it through a
    rolling steady-state sink without allocating a payload-sized
    buffer.  ``topic`` is ``None`` when the topic itself exceeded
    ``rx_buffer_size`` and couldn't be parsed.  ``reported_length`` is
    the MQTT remaining-length value (topic prelude + payload),
    diagnostic only — no payload bytes are recoverable.
    """

    def __init__(self, *, topic, reported_length, qos, packet_id):
        self.topic = topic
        self.reported_length = reported_length
        self.qos = qos
        self.packet_id = packet_id


# Drain modes used by PacketDecoder for an in-progress inbound PUBLISH
# that exceeded ``rx_buffer_size``.  ``_DRAIN_INTACT`` fills a one-shot
# payload-sized buffer (tier 2); ``_DRAIN_OVERSIZED`` rolls the payload
# through the steady-state buffer without keeping any of it (tier 3).
_DRAIN_NONE = const(0)
_DRAIN_INTACT = const(1)
_DRAIN_OVERSIZED = const(2)


class PacketDecoder:
    """Incremental MQTT packet parser with a three-tier inbound size model.

    Tier 1 (steady): packets ≤ ``rx_buffer_size`` parse inline from the
    pre-allocated steady-state buffer.  No allocation.

    Tier 2 (intact): packets > ``rx_buffer_size`` but ≤ ``max_message_bytes``.
    A one-shot ``bytearray(payload_length)`` is allocated for this
    message; payload drains through the steady-state buffer into it;
    :class:`ParsedPublish` is delivered with the full payload.  The
    intact buffer drops out of scope after delivery.

    Tier 3 (oversized): packets > ``max_message_bytes``.  No allocation
    beyond the steady-state buffer.  Payload drains via rolling
    discard — each pass refills the steady-state buffer from the
    socket, advances a "still to drain" counter, then resets for the
    next pass.  Emits :class:`_OversizedMessage` once drained; the
    payload bytes are gone.

    Usage::

        decoder = PacketDecoder(max_message_bytes=8192)
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
        max_message_bytes=DEFAULT_MAX_MESSAGE_BYTES,
    ):
        self._buffer = bytearray(rx_buffer_size)
        # Cached memoryview into ``_buffer`` — the steady-state buffer
        # is allocated once and never resized, so the view is stable
        # for the parser's lifetime.  Cached to avoid constructing a
        # fresh memoryview on every ``fill_buffer``/``read_next`` call
        # (per-packet hot path on a busy MQTT subscriber).
        self._buffer_view = memoryview(self._buffer)
        self._buffer_size = rx_buffer_size
        # Read-cursor pattern (mirrors :class:`chumicro_requests._wire.
        # ResponseParser`): ``_buffer_length`` is the write end, fed by
        # ``advance()``; ``_read_offset`` is the consume start, advanced
        # by ``_consume()``.  Each parsed packet bumps the cursor
        # without memmove.  Compaction (in-place memmove of the live
        # tail to the buffer head) only triggers when the cursor passes
        # the halfway mark, amortizing the per-packet allocation cost
        # of the old "shift after every drain" shape.
        self._buffer_length = 0
        self._read_offset = 0
        self._max_message_bytes = max_message_bytes
        # In-flight oversized-PUBLISH drain state.  ``_DRAIN_NONE`` while
        # the steady-state parse path is active; ``_DRAIN_INTACT`` while
        # filling a tier-2 payload buffer; ``_DRAIN_OVERSIZED`` while
        # rolling-discarding a tier-3 payload through the steady-state
        # buffer.
        self._drain_mode = _DRAIN_NONE
        self._drain_payload_buffer = None
        self._drain_payload_view = None
        self._drain_payload_filled = 0
        self._drain_payload_length = 0
        self._drain_remaining = 0          # tier-3 bytes still to consume from the socket
        self._drain_topic = None
        self._drain_qos = 0
        self._drain_retain = False
        self._drain_packet_id = None
        self._drain_message_length = 0     # MQTT remaining-length, reported back on oversize

    def fill_buffer(self):
        """Return the bytearray slice the next ``recv_into`` should write into."""
        if self._drain_mode == _DRAIN_INTACT:
            return self._drain_payload_view[self._drain_payload_filled:]
        # Oversized mode reuses the steady-state buffer as a rolling
        # sink — bytes are written, counted, and discarded.  Steady
        # mode appends to the cursor.
        return self._buffer_view[self._buffer_length:]

    def fill_capacity(self):
        """Bytes the parser is willing to receive on the next ``recv_into``."""
        if self._drain_mode == _DRAIN_INTACT:
            return self._drain_payload_length - self._drain_payload_filled
        if self._drain_mode == _DRAIN_OVERSIZED:
            # Each pass caps at the smaller of remaining-to-drain and
            # steady-state buffer space.  When the buffer fills,
            # ``advance`` resets it for the next pass.
            available = self._buffer_size - self._buffer_length
            return min(self._drain_remaining, available)
        return self._buffer_size - self._buffer_length

    def advance(self, nbytes):
        """Tell the parser *nbytes* were just written into the fill region."""
        if nbytes <= 0:
            return
        if self._drain_mode == _DRAIN_INTACT:
            self._drain_payload_filled += nbytes
            return
        if self._drain_mode == _DRAIN_OVERSIZED:
            self._drain_remaining -= nbytes
            # The bytes are being discarded — reset the rolling sink
            # for the next pass.  We never read them back.
            self._buffer_length = 0
            return
        self._buffer_length += nbytes

    def read_next(self):
        """Return the next complete packet, or ``None`` if more bytes needed.

        Returns one of: :class:`ParsedPublish`, :class:`ParsedAck`,
        :class:`_OversizedMessage`, or ``None``.  Raises
        :class:`MQTTProtocolError` on malformed input.
        """
        if self._drain_mode == _DRAIN_INTACT:
            return self._maybe_finish_intact()
        if self._drain_mode == _DRAIN_OVERSIZED:
            return self._maybe_finish_oversized()

        base = self._read_offset
        live = self._buffer_length - base
        # Need at least the fixed header byte + first remaining-length byte.
        if live < 2:
            return None

        # Use the cached view rather than constructing a fresh one
        # per call.  ``_buffer`` is allocated once at construction
        # and never resized, so the view is stable for the parser's
        # lifetime.
        view = self._buffer_view
        fixed_byte = view[base]
        message_length, varlen_consumed = decode_varlen(view, base + 1)
        if varlen_consumed == 0:
            return None  # Incomplete varlen — wait for more bytes.
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
            return None  # Body still in transit.

        body_start = base + header_length
        body_end = base + total_length
        packet = self._parse_packet(fixed_byte, view, body_start, body_end)
        self._consume(total_length)
        return packet

    def _consume(self, count):
        """Advance the read cursor by *count*; compact when half-consumed.

        Mirrors the read-cursor pattern in :class:`chumicro_requests._wire.
        ResponseParser._consume`: the per-packet cost is one integer
        add; the in-place memmove that frees up tail capacity only fires
        when the cursor passes the halfway mark.
        """
        self._read_offset += count
        if self._read_offset * 2 >= self._buffer_size:
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
        # qos bits are bits 1-2 of the fixed-header byte; retain is bit 0.
        qos = (fixed_byte >> 1) & 0x03
        retain = bool(fixed_byte & 0x01)
        # A PUBLISH shorter than its 2-byte topic-length prefix is
        # malformed; without this the struct.unpack below raises a raw
        # struct/ValueError the caller doesn't classify as protocol.
        if body_end - body_start < 2:
            raise MQTTProtocolError("PUBLISH missing 2-byte topic-length prefix")
        # ``struct.unpack`` accepts memoryview directly — no ``bytes()``
        # wrap needed, which would otherwise copy 2 bytes per integer
        # field (4-6 wasted allocs per PUBLISH).
        topic_length = struct.unpack(">H", view[body_start:body_start + 2])[0]
        topic_start = body_start + 2
        topic_end = topic_start + topic_length
        if topic_end > body_end:
            raise MQTTProtocolError("PUBLISH topic length exceeds remaining bytes")
        # 3-arg str() accepts a memoryview directly — skips the
        # bytes() copy that ``bytes(view[a:b]).decode()`` would do.
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

    def _enter_drain_path(self, *, fixed_byte, message_length, base, header_length, total_length):
        """Switch into drain mode for a packet that overflows the steady buffer.

        For a PUBLISH, the fixed header + varlen + topic-prelude
        (length-prefix + topic + optional packet_id) generally fits in
        the steady-state buffer; the payload doesn't.  Parse the
        prelude, then route into tier 2 (intact delivery, one-shot
        payload-sized buffer) or tier 3 (rolling discard, no extra
        allocation) based on ``total_length`` vs ``max_message_bytes``.

        Non-PUBLISH oversize is a protocol error — broker shouldn't be
        sending a 300-byte SUBACK.

        Topic-too-long case: when the prelude itself doesn't fit in
        the steady-state buffer (oversize topic + small rx buffer),
        fall through to tier 3 with ``topic=None``.  The caller can
        distinguish this case in its ``on_oversized`` handler.
        """
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
        retain = bool(fixed_byte & 0x01)
        packet_id_bytes = 2 if qos > 0 else 0
        prelude_length = header_length + 2 + topic_length + packet_id_bytes

        if prelude_length > self._buffer_size:
            # Oversize-topic: the topic itself doesn't fit in the
            # steady-state buffer, so we can't parse it (or the
            # packet_id, which sits after the topic).  Drain
            # everything that's still on the wire and emit an event
            # with topic=None.  The bytes already sitting in the
            # steady-state buffer (header + partial topic) get
            # discarded along with the rest.
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

        payload_length = message_length - 2 - topic_length - packet_id_bytes
        payload_already_in_steady = live - prelude_length

        if total_length <= self._max_message_bytes:
            # Tier 2: intact delivery.  Allocate a payload-sized
            # buffer, copy whatever's already in the steady-state
            # buffer into the head, drain the rest via the next
            # ``fill_buffer`` / ``advance`` calls.
            #
            # Buffer-absolute offset for the start of the carried-over
            # payload bytes: the packet starts at ``base`` in the
            # steady-state buffer, the prelude ends at
            # ``base + prelude_length``, so payload starts there.
            self._enter_intact_drain(
                topic=topic,
                qos=qos,
                retain=retain,
                packet_id=packet_id,
                payload_length=payload_length,
                payload_already_in_steady=payload_already_in_steady,
                payload_start_in_buffer=base + prelude_length,
                view=view,
            )
            return self._maybe_finish_intact()

        # Tier 3: oversized.  Discard the payload via rolling drain;
        # no extra allocation beyond the steady-state buffer.
        self._enter_oversized_drain(
            bytes_still_on_wire=total_length - live,
            topic=topic,
            qos=qos,
            packet_id=packet_id,
            message_length=message_length,
        )
        return self._maybe_finish_oversized()

    def _enter_intact_drain(
        self, *, topic, qos, retain, packet_id,
        payload_length, payload_already_in_steady, payload_start_in_buffer, view,
    ):
        """Allocate the tier-2 buffer and seed it with bytes already in steady."""
        # ``bytearray(0)`` is valid — empty-payload PUBLISH on a
        # too-small buffer enters tier 2 with payload_length=0 and
        # finishes immediately.
        self._drain_payload_buffer = bytearray(payload_length)
        self._drain_payload_view = memoryview(self._drain_payload_buffer)
        if payload_already_in_steady > 0:
            self._drain_payload_view[:payload_already_in_steady] = (
                view[payload_start_in_buffer:payload_start_in_buffer + payload_already_in_steady]
            )
        self._drain_payload_filled = payload_already_in_steady
        self._drain_payload_length = payload_length
        self._drain_topic = topic
        self._drain_qos = qos
        self._drain_retain = retain
        self._drain_packet_id = packet_id
        # Reset steady-state buffer — prelude + carried-over payload
        # bytes have been consumed.
        self._buffer_length = 0
        self._read_offset = 0
        self._drain_mode = _DRAIN_INTACT

    def _enter_oversized_drain(
        self, *, bytes_still_on_wire, topic, qos, packet_id, message_length,
    ):
        """Set up tier-3 drain state.  Reuses the steady-state buffer as a rolling sink."""
        self._drain_remaining = max(0, bytes_still_on_wire)
        self._drain_topic = topic
        self._drain_qos = qos
        self._drain_packet_id = packet_id
        self._drain_message_length = message_length
        # Discard anything still in the steady-state buffer — we've
        # extracted everything we need (prelude already parsed; tier-3
        # payload bytes aren't kept).
        self._buffer_length = 0
        self._read_offset = 0
        self._drain_mode = _DRAIN_OVERSIZED

    def _maybe_finish_intact(self):
        """Return a ParsedPublish if the intact buffer is full, else None."""
        if self._drain_payload_filled < self._drain_payload_length:
            return None
        payload = bytes(self._drain_payload_view[:self._drain_payload_length])
        packet = ParsedPublish(
            topic=self._drain_topic,
            payload=payload,
            qos=self._drain_qos,
            retain=self._drain_retain,
            packet_id=self._drain_packet_id,
        )
        self._reset_drain_state()
        return packet

    def _maybe_finish_oversized(self):
        """Return an _OversizedMessage if drain is complete, else None."""
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
        """Clear all in-flight drain state after a tier-2 or tier-3 message finishes."""
        self._drain_mode = _DRAIN_NONE
        self._drain_payload_buffer = None
        self._drain_payload_view = None
        self._drain_payload_filled = 0
        self._drain_payload_length = 0
        self._drain_remaining = 0
        self._drain_topic = None
        self._drain_qos = 0
        self._drain_retain = False
        self._drain_packet_id = None
        self._drain_message_length = 0
