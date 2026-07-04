"""Tests for the streaming inbound packet decoder."""

from chumicro_mqtt import MQTTProtocolError
from chumicro_mqtt._wire import (
    PACKET_CONNACK,
    PACKET_PINGRESP,
    PACKET_PUBACK,
    PACKET_SUBACK,
    PACKET_UNSUBACK,
    PacketDecoder,
    ParsedAck,
    ParsedPublish,
    _OversizedMessage,
    decode_varlen,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_pingresp_bytes,
    canned_puback_bytes,
    canned_publish_bytes,
    canned_suback_bytes,
    canned_unsuback_bytes,
)
from chumicro_test_harness.assertions import raises


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


class TestDecoderWedgeAndVarlen:
    def test_decode_varlen_stops_at_live_limit(self) -> None:
        # With a continuation byte but the live region ending right
        # after it, the scan must report incomplete instead of reading
        # stale trailing bytes as continuation.
        buffer = memoryview(b"\x81\xff\xff\xff")
        assert decode_varlen(buffer, 0, 1) == (0, 0)
        # A complete varlen within the limit decodes normally.
        assert decode_varlen(memoryview(b"\x81\x01"), 0, 2) == (129, 2)

    def test_incomplete_packet_compacts_instead_of_wedging(self) -> None:
        # rx=256.  Advance the read cursor below the halfway compaction
        # threshold with small packets, then feed a packet that fits the
        # buffer but not the space remaining past the cursor.  It must
        # complete rather than wedge with fill_capacity() stuck at 0.
        decoder = PacketDecoder(rx_buffer_size=256)
        small = canned_publish_bytes("t" * 20, b"x", qos=0)
        for _ in range(4):
            decoder.fill_buffer()[:len(small)] = small
            decoder.advance(len(small))
            assert isinstance(decoder.read_next(), ParsedPublish)
            assert decoder.read_next() is None

        big_payload = b"y" * 170
        big = canned_publish_bytes("b", big_payload, qos=0)
        assert len(big) <= 256  # fits the buffer as a whole
        parsed = None
        fed = 0
        # Bounded loop: a wedge would spin forever, so cap iterations and
        # assert capacity never sticks at 0 while the packet is partial.
        for _ in range(20):
            if fed < len(big):
                capacity = decoder.fill_capacity()
                assert capacity > 0, "fill_capacity wedged at 0 mid-packet"
                chunk = big[fed:fed + capacity]
                decoder.fill_buffer()[:len(chunk)] = chunk
                decoder.advance(len(chunk))
                fed += len(chunk)
            parsed = decoder.read_next()
            if parsed is not None:
                break
        assert isinstance(parsed, ParsedPublish)
        assert bytes(parsed.payload) == big_payload


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


class TestProtocolErrors:
    def test_unknown_packet_type(self) -> None:
        decoder = PacketDecoder()
        # 0xF0 is the reserved high-nibble for AUTH (MQTT 5 only).
        _feed(decoder, b"\xf0\x00")
        with raises(MQTTProtocolError):
            decoder.read_next()

    def test_publish_shorter_than_topic_length_prefix_raises(self) -> None:
        # PUBLISH (0x30) with a 0-byte body: no room for the 2-byte
        # topic-length prefix.  Must be a classified protocol error,
        # not a raw struct/ValueError from the unpack.
        decoder = PacketDecoder()
        _feed(decoder, b"\x30\x00")
        with raises(MQTTProtocolError):
            decoder.read_next()

    def test_oversized_simple_ack_raises(self) -> None:
        """SUBACK with body longer than buffer is a protocol error,
        not an oversize-message event."""
        decoder = PacketDecoder(rx_buffer_size=8)
        # Synthesize a SUBACK with body length > buffer.
        body_length = 100
        packet = bytes((0x90, body_length)) + b"\x00" * body_length
        # Feed enough to trip the size check.
        decoder.fill_buffer()[:2] = packet[:2]
        decoder.advance(2)
        with raises(MQTTProtocolError):
            decoder.read_next()


def _drive_until_done(decoder: PacketDecoder, packet: bytes, chunk_size: int = 32) -> list:
    """Feed *packet* through *decoder* in chunks, collecting parsed events."""
    events: list = []
    offset = 0
    while offset < len(packet):
        chunk = packet[offset:offset + chunk_size]
        offset += chunk_size
        room = decoder.fill_capacity()
        if room == 0:
            event = decoder.read_next()
            if event is not None:
                events.append(event)
            continue
        write = chunk[:room]
        decoder.fill_buffer()[:len(write)] = write
        decoder.advance(len(write))
        event = decoder.read_next()
        if event is not None:
            events.append(event)
    while True:
        event = decoder.read_next()
        if event is None:
            break
        events.append(event)
    return events


class TestOversizedTier:
    """Tier 2: a PUBLISH > rx_buffer_size delivers as _OversizedMessage (payload dropped)."""

    def test_publish_above_cap_drains_and_reports_length(self) -> None:
        decoder = PacketDecoder(
            rx_buffer_size=64,  # 200-byte payload overflows the steady buffer
        )
        big_payload = b"x" * 200
        packet = canned_publish_bytes("log", big_payload, qos=0)
        events = _drive_until_done(decoder, packet, chunk_size=32)
        oversized = [event for event in events if isinstance(event, _OversizedMessage)]
        assert len(oversized) == 1
        assert oversized[0].topic == "log"
        # reported_length is the MQTT remaining-length value
        # (topic prelude + payload).
        # topic_length_field (2) + "log" (3) + payload (200) = 205.
        assert oversized[0].reported_length == 205

    def test_oversize_topic_emits_none_topic(self) -> None:
        """When the topic alone exceeds rx_buffer_size, the oversized
        event reports topic=None (the topic can't be parsed)."""
        decoder = PacketDecoder(
            rx_buffer_size=16,        # tiny: even modest topics overflow
        )
        long_topic = "a" * 50
        packet = canned_publish_bytes(long_topic, b"x", qos=0)
        events = _drive_until_done(decoder, packet, chunk_size=8)
        oversized = [event for event in events if isinstance(event, _OversizedMessage)]
        assert len(oversized) == 1
        assert oversized[0].topic is None
        # Decoder should be back to steady state.  Feed a normal small
        # packet and verify it parses cleanly.
        small_packet = canned_publish_bytes("a", b"b", qos=0)
        events2 = _drive_until_done(decoder, small_packet, chunk_size=8)
        publishes = [event for event in events2 if isinstance(event, ParsedPublish)]
        assert len(publishes) == 1
        assert publishes[0].topic == "a"
