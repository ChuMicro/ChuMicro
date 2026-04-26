"""Pure-function packet encoders.

Stateless: every function takes the inputs it needs and returns the
fully-encoded bytes.  No reference to a client / socket / state
machine — keeps the encoders unit-testable and reusable.

The encoders all build a ``bytearray`` payload, prefix it with the
MQTT fixed header (packet type + variable-length-integer length), and
return the concatenation as ``bytes``.
"""

import struct

from chumicro_mqtt._errors import UnsupportedQoSError
from chumicro_mqtt._packets import (
    PACKET_CONNECT,
    PACKET_PUBLISH,
    PACKET_SUBSCRIBE,
    PACKET_UNSUBSCRIBE,
    encode_string,
    encode_varlen,
)

# ---------------------------------------------------------------------------
# CONNECT
# ---------------------------------------------------------------------------

#: MQTT 3.1.1 protocol-name + level prefix used in every CONNECT.
#:
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
            from the client side.
        clean_session: ``True`` (default) tells the broker to drop any
            session state for this client_id.  ``False`` resumes
            persistent state — used for QoS 1+ retransmission across
            reconnects.
        username / password: Optional auth credentials.  Both may be
            ``None`` for an unauthenticated connect.
        will_topic / will_message: "Last will" — broker publishes this
            on the user's behalf if the connection drops uncleanly.
        will_qos / will_retain: QoS + retain flags for the will message.

    Raises:
        UnsupportedQoSError: ``will_qos > 1``.
    """
    if will_qos > 1:
        raise UnsupportedQoSError(
            "will_qos must be 0 or 1; QoS 2 is reserved-not-implemented",
        )

    # CONNECT flags byte: bit-packed feature toggles.
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

    # Variable header.
    variable_header = bytearray(_CONNECT_PROTOCOL_PREFIX)
    variable_header.append(flags)
    variable_header.extend(struct.pack(">H", keep_alive_seconds))

    # Payload.
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


# ---------------------------------------------------------------------------
# PUBLISH
# ---------------------------------------------------------------------------


def encode_publish(*, topic, payload, qos=0, retain=False, packet_id=None):
    """Build a PUBLISH packet ready to send.

    *payload* is sent verbatim — encode it (UTF-8 / msgpack / raw bytes)
    before calling.  ``str`` payloads are auto-encoded as UTF-8 for
    convenience.

    Args:
        topic: Destination topic (str — encoded as UTF-8 by us).
        payload: Application bytes (or str — encoded as UTF-8 by us).
        qos: 0 or 1.  QoS 2 raises :class:`UnsupportedQoSError`.
        retain: True for retained messages.
        packet_id: Required for QoS > 0; pass ``None`` for QoS 0.

    Raises:
        UnsupportedQoSError: ``qos > 1``.
        ValueError: QoS > 0 without a *packet_id*.
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

    # Variable header: topic + (packet-id only when QoS > 0).
    variable_header = bytearray(encode_string(topic))
    if qos > 0:
        variable_header.extend(struct.pack(">H", packet_id))

    remaining = bytes(variable_header) + bytes(payload)
    return bytes(bytearray((fixed_byte_one,)) + encode_varlen(len(remaining))) + remaining


# ---------------------------------------------------------------------------
# SUBSCRIBE
# ---------------------------------------------------------------------------


def encode_subscribe(*, packet_id, subscriptions):
    """Build a SUBSCRIBE packet for one-or-more (topic, qos) pairs.

    Args:
        packet_id: 1-65535; allocate via :meth:`InFlightTable.allocate_id`
            (or your own counter).
        subscriptions: Iterable of ``(topic_str, qos_int)`` tuples.

    Raises:
        ValueError: Empty *subscriptions*; a SUBSCRIBE with zero filter
            is a protocol error.
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


# ---------------------------------------------------------------------------
# UNSUBSCRIBE
# ---------------------------------------------------------------------------


def encode_unsubscribe(*, packet_id, topics):
    """Build an UNSUBSCRIBE packet for one-or-more topics.

    Args:
        packet_id: 1-65535; same rules as SUBSCRIBE.
        topics: Iterable of topic strings.

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


# ---------------------------------------------------------------------------
# PUBACK — sent by the client in response to an inbound QoS 1 PUBLISH
# ---------------------------------------------------------------------------


def encode_puback(*, packet_id):
    """Build a PUBACK packet acknowledging a received QoS 1 PUBLISH."""
    # PUBACK fixed header is always 0x40 0x02 followed by the 2-byte packet-id.
    return bytes((0x40, 0x02)) + struct.pack(">H", packet_id)
