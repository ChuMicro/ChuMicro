"""Pre-baked broker responses and client fixtures for unit tests."""

__chumicro_test_support__ = True

import struct

from chumicro_mqtt.client import MQTTClient


def canned_connack_bytes(*, return_code: int = 0, session_present: bool = False) -> bytes:
    """Return the four-byte CONNACK packet for *return_code*.

    Args:
        return_code: 0 = accepted; 1-5 = rejection reasons (MQTT 3.1.1 §3.2.2.3).
        session_present: Bit 0 of the ack flags byte.
    """
    flags = 0x01 if session_present else 0x00
    return bytes((0x20, 0x02, flags, return_code))


def canned_puback_bytes(packet_id):
    """Return the four-byte PUBACK packet for *packet_id*."""
    return bytes((0x40, 0x02)) + struct.pack(">H", packet_id)


def canned_suback_bytes(packet_id, granted_qos=0):
    """Return a one-subscription SUBACK with *granted_qos*."""
    body = struct.pack(">H", packet_id) + bytes((granted_qos,))
    return bytes((0x90, len(body))) + body


def canned_unsuback_bytes(packet_id):
    """Return the four-byte UNSUBACK packet for *packet_id*."""
    return bytes((0xB0, 0x02)) + struct.pack(">H", packet_id)


def canned_pingresp_bytes():
    """Return the two-byte PINGRESP packet."""
    return b"\xd0\x00"


def canned_publish_bytes(topic, payload, *, qos=0, retain=False, packet_id=None):
    """Return a PUBLISH packet shaped like the broker would send."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if isinstance(topic, str):
        topic_bytes = topic.encode("utf-8")
    else:
        topic_bytes = topic
    fixed_byte_one = 0x30 | (qos << 1)
    if retain:
        fixed_byte_one |= 0x01
    variable_header = struct.pack(">H", len(topic_bytes)) + topic_bytes
    if qos > 0:
        if packet_id is None:
            raise ValueError("QoS > 0 PUBLISH requires a packet_id")
        variable_header += struct.pack(">H", packet_id)
    body = variable_header + payload
    # Variable-length encoding of the body length.
    remaining_bytes = bytearray()
    value = len(body)
    while True:
        digit = value & 0x7F
        value >>= 7
        if value > 0:
            digit |= 0x80
        remaining_bytes.append(digit)
        if value == 0:
            break
    return bytes((fixed_byte_one,)) + bytes(remaining_bytes) + body


def new_client(sock, ticks, **overrides):
    """Build an MQTTClient against *sock* and *ticks* with test defaults."""
    kwargs = {
        "client_id": "test-client",
        "keep_alive_seconds": 60,
        "ack_timeout_seconds": 5.0,
        "publish_retry_max": 2,
        "ticks": ticks,
    }
    kwargs.update(overrides)
    return MQTTClient(sock, **kwargs)


def drive(client, ticks, count=1):
    """Call ``client.handle(ticks.ticks_ms())`` *count* times in a row."""
    for _ in range(count):
        client.handle(ticks.ticks_ms())
