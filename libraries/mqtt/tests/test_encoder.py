"""Tests for the packet encoders."""

from chumicro_mqtt import (
    UnsupportedQoSError,
    encode_connect,
    encode_puback,
    encode_publish,
    encode_subscribe,
    encode_unsubscribe,
)
from chumicro_test_harness.assertions import raises


class TestEncodeConnect:
    def test_minimal_connect(self) -> None:
        packet = encode_connect(client_id="abc", keep_alive_seconds=60)
        # First byte: PACKET_CONNECT = 0x10.
        assert packet[0] == 0x10
        # The protocol prefix appears after the fixed header.
        assert b"\x00\x04MQTT\x04" in packet
        # Connect-flags byte has clean_session bit set (default).
        flags_index = packet.index(b"\x00\x04MQTT\x04") + len(b"\x00\x04MQTT\x04")
        assert packet[flags_index] & 0x02

    def test_username_password_set_flags(self) -> None:
        packet = encode_connect(
            client_id="abc",
            keep_alive_seconds=60,
            username="alice",
            password="hunter2",
        )
        flags_index = packet.index(b"\x00\x04MQTT\x04") + len(b"\x00\x04MQTT\x04")
        flags = packet[flags_index]
        assert flags & 0x80  # username
        assert flags & 0x40  # password

    def test_will_message_packs(self) -> None:
        packet = encode_connect(
            client_id="abc",
            keep_alive_seconds=60,
            will_topic="last/will",
            will_message=b"goodbye",
            will_qos=1,
            will_retain=True,
        )
        flags_index = packet.index(b"\x00\x04MQTT\x04") + len(b"\x00\x04MQTT\x04")
        flags = packet[flags_index]
        assert flags & 0x04  # will flag
        assert flags & (1 << 3)  # will qos = 1
        assert flags & 0x20  # will retain
        assert b"last/will" in packet
        assert b"goodbye" in packet

    def test_will_qos_two_raises(self) -> None:
        with raises(UnsupportedQoSError):
            encode_connect(
                client_id="abc",
                keep_alive_seconds=60,
                will_topic="x",
                will_message=b"y",
                will_qos=2,
            )


class TestEncodePublish:
    def test_qos_zero_no_packet_id(self) -> None:
        packet = encode_publish(topic="sensors/t", payload=b"42", qos=0)
        # First byte: PACKET_PUBLISH = 0x30, qos shifted in.
        assert packet[0] == 0x30
        assert b"sensors/t" in packet
        assert packet.endswith(b"42")

    def test_qos_one_includes_packet_id(self) -> None:
        packet = encode_publish(
            topic="sensors/t", payload=b"42", qos=1, packet_id=1234,
        )
        assert packet[0] == 0x30 | (1 << 1)  # qos = 1 in fixed-header byte
        # packet_id 1234 = 0x04D2
        assert b"\x04\xd2" in packet

    def test_qos_one_without_packet_id_raises(self) -> None:
        with raises(ValueError):
            encode_publish(topic="x", payload=b"y", qos=1)

    def test_retain_sets_low_bit(self) -> None:
        packet = encode_publish(topic="x", payload=b"y", qos=0, retain=True)
        assert packet[0] & 0x01

    def test_str_payload_is_utf8_encoded(self) -> None:
        packet = encode_publish(topic="x", payload="hello", qos=0)
        assert packet.endswith(b"hello")

    def test_qos_two_raises(self) -> None:
        with raises(UnsupportedQoSError):
            encode_publish(topic="x", payload=b"y", qos=2)


class TestEncodeSubscribe:
    def test_single_subscription(self) -> None:
        packet = encode_subscribe(packet_id=42, subscriptions=[("sensors/+", 1)])
        # Fixed-header first byte must be 0x82 per spec.
        assert packet[0] == 0x82
        # packet_id 42 = 0x002A.
        assert b"\x00\x2a" in packet
        # qos 1 byte at the end.
        assert packet.endswith(b"\x01")
        assert b"sensors/+" in packet

    def test_multiple_subscriptions(self) -> None:
        packet = encode_subscribe(
            packet_id=99,
            subscriptions=[("a", 0), ("b", 1)],
        )
        assert b"a" in packet
        assert b"b" in packet

    def test_empty_subscriptions_raises(self) -> None:
        with raises(ValueError):
            encode_subscribe(packet_id=1, subscriptions=[])

    def test_qos_two_subscription_raises(self) -> None:
        with raises(UnsupportedQoSError):
            encode_subscribe(packet_id=1, subscriptions=[("x", 2)])


class TestEncodeUnsubscribe:
    def test_single_topic(self) -> None:
        packet = encode_unsubscribe(packet_id=99, topics=["a/b"])
        assert packet[0] == 0xA2
        assert b"a/b" in packet

    def test_multiple_topics(self) -> None:
        packet = encode_unsubscribe(packet_id=1, topics=["a", "b"])
        assert b"a" in packet
        assert b"b" in packet

    def test_empty_raises(self) -> None:
        with raises(ValueError):
            encode_unsubscribe(packet_id=1, topics=[])


class TestEncodePuback:
    def test_canonical_shape(self) -> None:
        packet = encode_puback(packet_id=42)
        assert packet == b"\x40\x02\x00\x2a"

    def test_packet_id_zero_padding(self) -> None:
        packet = encode_puback(packet_id=1)
        assert packet == b"\x40\x02\x00\x01"
