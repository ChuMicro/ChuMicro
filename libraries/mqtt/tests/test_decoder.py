"""Tests for the streaming inbound packet decoder (parsing happy paths).

The edge / fault paths — varlen wedge, protocol errors, the oversized
tier — live in ``test_decoder_error_paths.py`` (suite-slimming split).
"""

from chumicro_mqtt._wire import (
    PACKET_CONNACK,
    PACKET_PINGRESP,
    PACKET_PUBACK,
    PACKET_SUBACK,
    PACKET_UNSUBACK,
    PacketDecoder,
    ParsedAck,
    ParsedPublish,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_pingresp_bytes,
    canned_puback_bytes,
    canned_publish_bytes,
    canned_suback_bytes,
    canned_unsuback_bytes,
)


def _feed(decoder: PacketDecoder, payload: bytes) -> None:
    """Stuff *payload* into the decoder via fill_buffer/advance."""
    while payload:
        room = decoder.fill_capacity()
        chunk = payload[:room]
        decoder.fill_buffer()[:len(chunk)] = chunk
        decoder.advance(len(chunk))
        payload = payload[room:]
        if not payload:
            break


class TestParseAcks:
    def test_connack_success(self) -> None:
        decoder = PacketDecoder()
        _feed(decoder, canned_connack_bytes(return_code=0))
        packet = decoder.read_next()
        assert isinstance(packet, ParsedAck)
        assert packet.packet_type == PACKET_CONNACK
        assert packet.return_code == 0

    def test_connack_with_rejection(self) -> None:
        decoder = PacketDecoder()
        _feed(decoder, canned_connack_bytes(return_code=5))
        packet = decoder.read_next()
        assert packet.return_code == 5

    def test_puback(self) -> None:
        decoder = PacketDecoder()
        _feed(decoder, canned_puback_bytes(packet_id=4242))
        packet = decoder.read_next()
        assert packet.packet_type == PACKET_PUBACK
        assert packet.packet_id == 4242

    def test_suback(self) -> None:
        decoder = PacketDecoder()
        _feed(decoder, canned_suback_bytes(packet_id=99, granted_qos=1))
        packet = decoder.read_next()
        assert packet.packet_type == PACKET_SUBACK
        assert packet.packet_id == 99
        assert packet.granted_qos == [1]

    def test_unsuback(self) -> None:
        decoder = PacketDecoder()
        _feed(decoder, canned_unsuback_bytes(packet_id=88))
        packet = decoder.read_next()
        assert packet.packet_type == PACKET_UNSUBACK
        assert packet.packet_id == 88

    def test_pingresp(self) -> None:
        decoder = PacketDecoder()
        _feed(decoder, canned_pingresp_bytes())
        packet = decoder.read_next()
        assert packet.packet_type == PACKET_PINGRESP


class TestParsePublish:
    def test_qos_zero(self) -> None:
        decoder = PacketDecoder()
        _feed(decoder, canned_publish_bytes("temp", b"42", qos=0))
        packet = decoder.read_next()
        assert isinstance(packet, ParsedPublish)
        assert packet.topic == "temp"
        assert packet.payload == b"42"
        assert packet.qos == 0
        assert packet.retain is False
        assert packet.packet_id is None

    def test_qos_one_includes_packet_id(self) -> None:
        decoder = PacketDecoder()
        _feed(
            decoder,
            canned_publish_bytes("temp", b"99", qos=1, packet_id=1234),
        )
        packet = decoder.read_next()
        assert packet.qos == 1
        assert packet.packet_id == 1234
        assert packet.payload == b"99"

    def test_retain_flag(self) -> None:
        decoder = PacketDecoder()
        _feed(decoder, canned_publish_bytes("status", b"on", qos=0, retain=True))
        packet = decoder.read_next()
        assert packet.retain is True

    def test_unicode_topic(self) -> None:
        decoder = PacketDecoder()
        _feed(decoder, canned_publish_bytes("café/temperature", b"21", qos=0))
        packet = decoder.read_next()
        assert packet.topic == "café/temperature"

    def test_empty_payload(self) -> None:
        decoder = PacketDecoder()
        _feed(decoder, canned_publish_bytes("status", b"", qos=0))
        packet = decoder.read_next()
        assert packet.payload == b""


class TestStreaming:
    def test_partial_then_complete(self) -> None:
        """Half a packet first.  Second feed completes it."""
        decoder = PacketDecoder()
        whole = canned_connack_bytes(return_code=0)
        _feed(decoder, whole[:2])
        assert decoder.read_next() is None
        _feed(decoder, whole[2:])
        packet = decoder.read_next()
        assert packet.packet_type == PACKET_CONNACK

    def test_two_packets_back_to_back(self) -> None:
        """One feed delivers two packets."""
        decoder = PacketDecoder()
        connack = canned_connack_bytes(return_code=0)
        publish = canned_publish_bytes("t", b"x", qos=0)
        _feed(decoder, connack + publish)
        first = decoder.read_next()
        second = decoder.read_next()
        third = decoder.read_next()
        assert first.packet_type == PACKET_CONNACK
        assert isinstance(second, ParsedPublish)
        assert third is None

    def test_one_byte_at_a_time(self) -> None:
        """Trickled bytes still parse cleanly.  Every byte is individually fed."""
        decoder = PacketDecoder()
        whole = canned_publish_bytes("hello", b"world", qos=0)
        for byte_value in whole:
            decoder.fill_buffer()[:1] = bytes([byte_value])
            decoder.advance(1)
        packet = decoder.read_next()
        assert packet.topic == "hello"
        assert packet.payload == b"world"
