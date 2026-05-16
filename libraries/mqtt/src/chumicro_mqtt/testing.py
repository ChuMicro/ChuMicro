"""Pre-baked broker responses for unit tests.

Tests typically drive :class:`MQTTClient` via a
:class:`chumicro_sockets.testing.FakeSocket` — script broker
responses with ``sock.enqueue_recv(canned_connack_bytes())`` etc., let
the client tick, then assert the wire-format on ``sock.sent``.

These canned-bytes helpers stay in sync with the encoder/decoder so a
hand-rolled byte literal in a test doesn't drift when the wire format
gets a tweak.
"""

#: Test-support: PyPI sdist / wheel only -- bundles and product /
#: app / functional device deploys exclude it; the on-device unit
#: sweep is the one path that stages it.
__chumicro_test_support__ = True

import struct


def canned_connack_bytes(*, return_code: int = 0, session_present: bool = False) -> bytes:
    """Return the four-byte CONNACK packet for *return_code*.

    Args:
        return_code: 0 = accepted; 1-5 = various rejection reasons
            per MQTT 3.1.1 §3.2.2.3.  Tests for the rejection path
            pass non-zero here.
        session_present: Bit 0 of the ack flags byte.  ``True`` only
            on a clean_session=False resume.
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
    """Return a PUBLISH packet shaped like the broker would send.

    Mirrors :func:`chumicro_mqtt.encode_publish` but takes the same
    args downstream tests use.  Keep this in sync with the encoder
    if you tweak the wire format.
    """
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
    # Variable-length encoding for body length.
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
