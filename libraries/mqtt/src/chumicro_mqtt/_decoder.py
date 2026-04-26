"""Inbound-packet parser.

Stateful: holds a pre-allocated RX buffer that callers feed bytes
into incrementally.  ``read_next()`` returns the next complete packet
or ``None`` when more bytes are needed.

Buffer sizing follows pythonProject3's pattern: 256 bytes for the
common case, with an overflow path that allocates a one-shot
"degraded" buffer for oversized messages.  The library never holds
the degraded buffer beyond one parse cycle — its capacity is the
caller's choice (driven by ``max_message_size``).

Decision 0029 Phase 6 §"Oversized-message policy" introduces a
``WhenOversized`` enum.  This module raises a structured event
(:class:`_OversizedMessage`) that the client layer translates into
the user-configured policy (DROP_SILENT / DROP_WITH_EVENT /
DISCONNECT).
"""

import struct

from chumicro_mqtt._errors import MQTTProtocolError
from chumicro_mqtt._packets import (
    PACKET_CONNACK,
    PACKET_PINGRESP,
    PACKET_PUBACK,
    PACKET_PUBLISH,
    PACKET_SUBACK,
    PACKET_UNSUBACK,
    decode_varlen,
)

# ---------------------------------------------------------------------------
# Default buffer sizes (Decision 0029 Phase 6 §"Pre-allocated 256 B static
# RX buffer plus the degraded-state partial buffer for oversized messages")
# ---------------------------------------------------------------------------

#: Default pre-allocated steady-state buffer.  Most MQTT control
#: packets fit; small PUBLISH payloads ride along.
DEFAULT_RX_BUFFER_SIZE = 256

#: Default cap on a single inbound message.  Anything bigger triggers
#: the user-configured ``WhenOversized`` policy.
DEFAULT_MAX_MESSAGE_SIZE = 256 * 1024


# ---------------------------------------------------------------------------
# Parsed-packet shapes — small named tuples with named .fields the client uses
# ---------------------------------------------------------------------------


class ParsedPublish:
    """Inbound PUBLISH parsed off the wire.

    *payload* is a memoryview into the RX buffer — the client's
    callback must consume it before the next ``read_next()`` call,
    OR copy the bytes.  Cheap by design: most payloads land in user
    storage immediately and don't need a copy.
    """

    __slots__ = ("packet_id", "payload", "qos", "retain", "topic")

    def __init__(self, *, topic, payload, qos, retain, packet_id):
        self.topic = topic
        self.payload = payload
        self.qos = qos
        self.retain = retain
        self.packet_id = packet_id


class ParsedAck:
    """Inbound CONNACK / PUBACK / SUBACK / UNSUBACK / PINGRESP.

    A single shape covers all five.  ``packet_type`` is the wire
    constant; ``packet_id`` is None for CONNACK / PINGRESP and the
    16-bit id for PUBACK / SUBACK / UNSUBACK.  *return_code* is set
    only on CONNACK (zero == success); ``granted_qos`` is set only
    on SUBACK (one byte per requested filter).
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
    """Signal: the next message exceeds ``max_message_size``.

    The client decides what to do based on its ``WhenOversized``
    policy.  Carries the topic + reported length so DROP_WITH_EVENT
    can fire ``on_oversized(topic, reported_length)`` even though
    the payload was discarded.
    """

    __slots__ = ("packet_id", "qos", "reported_length", "topic")

    def __init__(self, *, topic, reported_length, qos, packet_id):
        self.topic = topic
        self.reported_length = reported_length
        self.qos = qos
        self.packet_id = packet_id


# ---------------------------------------------------------------------------
# Streaming parser
# ---------------------------------------------------------------------------


class PacketDecoder:
    """Incremental MQTT packet parser with a pre-allocated RX buffer.

    Usage::

        decoder = PacketDecoder()
        # Each tick:
        nbytes = sock.recv_into(decoder.fill_buffer(), decoder.fill_capacity())
        decoder.advance(nbytes)
        while True:
            packet = decoder.read_next()
            if packet is None:
                break
            # packet is ParsedPublish / ParsedAck / _OversizedMessage
            handle(packet)

    Two-buffer pattern: the steady-state buffer is reused tick-after-
    tick; oversize messages allocate a one-shot "degraded" buffer of
    the right size + drain into it.  Once the oversized message is
    consumed (or discarded), the parser returns to steady-state.
    """

    def __init__(
        self,
        *,
        rx_buffer_size=DEFAULT_RX_BUFFER_SIZE,
        max_message_size=DEFAULT_MAX_MESSAGE_SIZE,
    ):
        self._buffer = bytearray(rx_buffer_size)
        self._buffer_size = rx_buffer_size
        self._buffer_length = 0
        self._max_message_size = max_message_size
        # Degraded path — one-shot buffer for oversize messages whose
        # bodies don't fit into the steady-state buffer.  Used for
        # passthrough only when the client picks DROP_WITH_EVENT — we
        # have to drain the bytes off the wire to recover sync.
        self._degraded_buffer = None
        self._degraded_total = 0  # Total expected bytes for the degraded msg
        self._degraded_consumed = 0
        self._degraded_topic = None
        self._degraded_qos = 0
        self._degraded_packet_id = None

    # -- buffer-filling API the client drives ---------------------------

    def fill_buffer(self):
        """Return the bytearray slice the next ``recv_into`` should write into.

        Returns a memoryview of the unused tail of the steady-state
        buffer.  The client passes ``fill_capacity()`` as nbytes to
        cap the read at the available room.  When ``fill_capacity()``
        is 0 the parser is full; the client must drain via
        ``read_next()`` before pulling more bytes off the socket.
        """
        if self._degraded_buffer is not None:
            # In degraded mode: we drain into the dedicated buffer.
            return memoryview(self._degraded_buffer)[self._degraded_consumed:]
        return memoryview(self._buffer)[self._buffer_length:]

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

    # -- the read_next state machine ------------------------------------

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

        view = memoryview(self._buffer)
        fixed_byte = view[0]
        message_length, varlen_consumed = decode_varlen(view, 1)
        if varlen_consumed == 0:
            # Incomplete varlen — wait for more bytes.
            return None
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

    # -- packet body parsers --------------------------------------------

    def _parse_packet(self, fixed_byte, view, body_start, body_end):
        """Dispatch on packet type."""
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
        """Parse PUBLISH variable-header + payload."""
        # qos bits are bits 1-2 of the fixed-header byte; retain is bit 0.
        qos = (fixed_byte >> 1) & 0x03
        retain = bool(fixed_byte & 0x01)
        topic_length = struct.unpack(">H", bytes(view[body_start:body_start + 2]))[0]
        topic_start = body_start + 2
        topic_end = topic_start + topic_length
        if topic_end > body_end:
            raise MQTTProtocolError("PUBLISH topic length exceeds remaining bytes")
        topic = bytes(view[topic_start:topic_end]).decode("utf-8")
        cursor = topic_end
        packet_id = None
        if qos > 0:
            if cursor + 2 > body_end:
                raise MQTTProtocolError(
                    "QoS > 0 PUBLISH missing 2-byte packet identifier",
                )
            packet_id = struct.unpack(
                ">H", bytes(view[cursor:cursor + 2]),
            )[0]
            cursor += 2
        # Payload is everything left in the body.  Return a memoryview
        # so the client can avoid a copy when handing it to user code.
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
        packet_id = struct.unpack(
            ">H", bytes(view[body_start:body_start + 2]),
        )[0]
        return ParsedAck(packet_type=packet_type, packet_id=packet_id)

    def _parse_suback(self, view, body_start, body_end):
        body_length = body_end - body_start
        if body_length < 3:
            raise MQTTProtocolError("SUBACK body must be at least 3 bytes")
        packet_id = struct.unpack(
            ">H", bytes(view[body_start:body_start + 2]),
        )[0]
        granted_qos = list(view[body_start + 2:body_end])
        return ParsedAck(
            packet_type=PACKET_SUBACK,
            packet_id=packet_id,
            granted_qos=granted_qos,
        )

    # -- oversized path -------------------------------------------------

    def _enter_oversized_path(self, fixed_byte, message_length, view, header_length):
        """Switch to degraded-buffer mode for a too-big message.

        The variable header (topic + optional packet-id for PUBLISH)
        likely fits in the steady-state buffer; the payload doesn't.
        We pull what we have, parse the topic, then read-and-discard
        the remaining payload bytes to recover sync.

        For non-PUBLISH packets that are oversized (very rare —
        SUBACK/PUBACK can't legitimately exceed our buffer), this is
        a protocol error.
        """
        packet_type = fixed_byte & 0xF0
        if packet_type != PACKET_PUBLISH:
            raise MQTTProtocolError(
                f"oversized non-PUBLISH packet (type 0x{packet_type:02X}, "
                f"remaining length {message_length})",
            )
        body_start = header_length
        # We need at least 2 bytes for the topic length.
        if self._buffer_length < body_start + 2:
            return None  # Need a few more bytes before we can parse the topic.
        topic_length = struct.unpack(
            ">H",
            bytes(memoryview(self._buffer)[body_start:body_start + 2]),
        )[0]
        topic_start = body_start + 2
        topic_end = topic_start + topic_length
        # qos bits + packet-id bytes if applicable.
        qos = (fixed_byte >> 1) & 0x03
        packet_id_bytes = 2 if qos > 0 else 0
        prelude_total = topic_end + packet_id_bytes
        if self._buffer_length < prelude_total:
            return None  # Need a few more bytes before we can parse the prelude.
        topic = bytes(memoryview(self._buffer)[topic_start:topic_end]).decode("utf-8")
        packet_id = None
        if qos > 0:
            packet_id = struct.unpack(
                ">H",
                bytes(memoryview(self._buffer)[topic_end:topic_end + 2]),
            )[0]
        # Switch to degraded mode: allocate a sink buffer for the
        # remaining payload bytes (we discard them but have to drain
        # them to recover sync).
        payload_remaining = (
            (header_length + message_length) - prelude_total
        )
        # Drop everything we've already consumed from the steady-state
        # buffer.
        body_already_in_steady = self._buffer_length - prelude_total
        # Sink buffer holds the rest of the payload only.
        payload_to_drain = payload_remaining - body_already_in_steady
        if payload_to_drain <= 0:
            # Whole oversized message is already in the steady-state
            # buffer (extreme corner case where the buffer is huge but
            # max_message_size is even larger).  Degenerate to an
            # immediate _OversizedMessage event and reset the buffer.
            self._buffer_length = 0
            return _OversizedMessage(
                topic=topic,
                reported_length=message_length,
                qos=qos,
                packet_id=packet_id,
            )
        # Normal path: drain into a degraded buffer.
        self._degraded_buffer = bytearray(payload_to_drain)
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
        # Drained — emit the event + reset.
        event = _OversizedMessage(
            topic=self._degraded_topic,
            reported_length=self._degraded_total,
            qos=self._degraded_qos,
            packet_id=self._degraded_packet_id,
        )
        self._degraded_buffer = None
        self._degraded_total = 0
        self._degraded_consumed = 0
        self._degraded_topic = None
        self._degraded_qos = 0
        self._degraded_packet_id = None
        return event
