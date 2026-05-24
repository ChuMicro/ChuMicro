"""Tests for the canned-bytes helpers in chumicro_mqtt.testing."""

from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_pingresp_bytes,
    canned_puback_bytes,
    canned_publish_bytes,
    canned_suback_bytes,
    canned_unsuback_bytes,
)
from chumicro_test_harness.assertions import raises


class TestCannedConnack:
    def test_default_is_accepted(self) -> None:
        packet = canned_connack_bytes()
        assert packet == b"\x20\x02\x00\x00"

    def test_session_present_sets_bit(self) -> None:
        packet = canned_connack_bytes(session_present=True)
        assert packet[2] == 0x01

    def test_rejection_carries_return_code(self) -> None:
        packet = canned_connack_bytes(return_code=4)
        assert packet[3] == 4


class TestCannedPuback:
    def test_packet_id_packed_big_endian(self) -> None:
        packet = canned_puback_bytes(packet_id=4242)
        assert packet == b"\x40\x02\x10\x92"


class TestCannedSuback:
    def test_default_qos_zero(self) -> None:
        packet = canned_suback_bytes(packet_id=99)
        assert packet[-1] == 0  # granted_qos = 0

    def test_explicit_qos(self) -> None:
        packet = canned_suback_bytes(packet_id=99, granted_qos=1)
        assert packet[-1] == 1


class TestCannedUnsuback:
    def test_known_encoding(self) -> None:
        packet = canned_unsuback_bytes(packet_id=42)
        assert packet == b"\xb0\x02\x00\x2a"


class TestCannedPingresp:
    def test_known_encoding(self) -> None:
        assert canned_pingresp_bytes() == b"\xd0\x00"


class TestCannedPublish:
    def test_str_payload_utf8_encoded(self) -> None:
        packet = canned_publish_bytes("temp", "hello", qos=0)
        assert packet.endswith(b"hello")

    def test_bytes_topic_passes_through(self) -> None:
        packet = canned_publish_bytes(b"temp", b"21", qos=0)
        assert b"temp" in packet

    def test_qos_one_includes_packet_id(self) -> None:
        packet = canned_publish_bytes("topic", b"x", qos=1, packet_id=42)
        # packet_id 42 = 0x002A appears in the variable header.
        assert b"\x00\x2a" in packet

    def test_qos_one_without_packet_id_raises(self) -> None:
        with raises(ValueError):
            canned_publish_bytes("topic", b"x", qos=1)

    def test_retain_flag(self) -> None:
        packet = canned_publish_bytes("topic", b"x", qos=0, retain=True)
        assert packet[0] & 0x01

    def test_long_payload_uses_multibyte_varlen(self) -> None:
        # A 200-byte payload needs a 2-byte varlen on the wire.
        packet = canned_publish_bytes("t", b"x" * 200, qos=0)
        # Body is 2 (topic length) + 1 (topic 't') + 200 = 203 bytes.
        # Varlen encoding of 203: [0xCB, 0x01]
        assert packet[1] == 0xCB
        assert packet[2] == 0x01
