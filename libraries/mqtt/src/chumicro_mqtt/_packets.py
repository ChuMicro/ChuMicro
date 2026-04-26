"""MQTT 3.1.1 wire-format primitives.

These five helpers (variable-length-integer codec, length-prefixed
string codec, topic-pattern matcher) are pulled mostly verbatim from
the pythonProject3 client — they're the solid parts that didn't get
weird.  Everything else in this package builds on top of them.

The constants are spelt out as ``const(...)`` where the runtime
supports it (saves a few bytes per reference on MP).  Falls back to
plain integers on CPython.
"""

import struct

try:
    from micropython import const
except ImportError:
    def const(value):
        return value


# ---------------------------------------------------------------------------
# Packet types — first byte of the fixed header (with flags zero'd)
# ---------------------------------------------------------------------------

#: CONNECT — first packet on a fresh socket.
PACKET_CONNECT = const(0x10)

#: CONNACK — broker's response to CONNECT.
PACKET_CONNACK = const(0x20)

#: PUBLISH — application message in either direction.
PACKET_PUBLISH = const(0x30)

#: PUBACK — broker's QoS 1 ack for an inbound PUBLISH.
PACKET_PUBACK = const(0x40)

#: SUBSCRIBE — client requests a subscription.
PACKET_SUBSCRIBE = const(0x82)

#: SUBACK — broker's response to SUBSCRIBE.
PACKET_SUBACK = const(0x90)

#: UNSUBSCRIBE — client cancels a subscription.
PACKET_UNSUBSCRIBE = const(0xA2)

#: UNSUBACK — broker's response to UNSUBSCRIBE.
PACKET_UNSUBACK = const(0xB0)

#: Pre-encoded PINGREQ.  No payload, two bytes total.
PACKET_PINGREQ = b"\xc0\x00"

#: PINGRESP — broker's response to PINGREQ.
PACKET_PINGRESP = const(0xD0)

#: Pre-encoded DISCONNECT.  No payload, two bytes total.
PACKET_DISCONNECT = b"\xe0\x00"

# ---------------------------------------------------------------------------
# Reserved for QoS 2 (Decision 0029 §"Allow but don't implement").  Tests
# assert these constants exist at the canonical values so future work
# can wire handlers without an audit pass.
# ---------------------------------------------------------------------------

#: PUBREC — first half of QoS 2.  Reserved; not implemented.
PACKET_PUBREC = const(0x50)

#: PUBREL — second half of QoS 2.  Reserved; not implemented.
PACKET_PUBREL = const(0x62)

#: PUBCOMP — third half of QoS 2.  Reserved; not implemented.
PACKET_PUBCOMP = const(0x70)


# ---------------------------------------------------------------------------
# Codec helpers
# ---------------------------------------------------------------------------


def encode_varlen(value):
    """Encode *value* as an MQTT variable-length integer.

    MQTT uses a 7-bits-per-byte little-endian encoding for "remaining
    length" fields, so packets can grow up to 256 MB while a small
    message takes a single byte.  Bit 7 of each byte is the
    continuation flag — set means "another byte follows".

    Returns a bytearray (1-4 bytes).  Raises :class:`ValueError` on
    inputs above the spec maximum (268_435_455).
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

    Returns ``(value, bytes_consumed)``.  When the buffer doesn't
    contain a complete varlen at *start_index*, returns ``(0, 0)`` —
    the caller knows to pull more bytes and retry.

    Args:
        buffer: ``bytes`` / ``bytearray`` / ``memoryview``.
        start_index: Offset of the first byte to decode.
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
    """Encode *value* as an MQTT length-prefixed string.

    MQTT string fields are ``2-byte big-endian length || UTF-8 bytes``.
    *value* may be a ``str`` (gets ``.encode("utf-8")``) or already-
    encoded bytes.  Returns ``bytes``.
    """
    if isinstance(value, str):
        value = value.encode("utf-8")
    return struct.pack(">H", len(value)) + value


def topic_matches(topic, pattern):
    """Return ``True`` when *topic* matches the wildcard *pattern*.

    MQTT wildcard semantics:

    * ``+`` matches exactly one topic level.
    * ``#`` matches any number of topic levels; must be the last
      character in the pattern.

    Both *topic* and *pattern* are ``str`` (paths are joined by ``/``).
    """
    topic_levels = topic.split("/")
    pattern_levels = pattern.split("/")

    for index, pattern_level in enumerate(pattern_levels):
        if pattern_level == "#":
            # '#' must be the last pattern level.
            return index == len(pattern_levels) - 1
        if pattern_level == "+":
            # '+' matches one level; ensure topic has a level here.
            if index >= len(topic_levels):
                return False
            continue
        # Exact match required.
        if index >= len(topic_levels) or pattern_level != topic_levels[index]:
            return False

    # After processing all pattern levels, the topic shouldn't have
    # leftover levels (otherwise we partial-matched).
    return len(pattern_levels) == len(topic_levels)
