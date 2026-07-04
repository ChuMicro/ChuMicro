"""mqtt client: malformed broker bytes fault cleanly to FAILED (decode edges).

The negative suite's B/C/D rows exercise "the broker/network sends
something wrong".  The pure protocol-decode edges of that — a malformed
CONNACK, a remaining-length varlen that overruns the 4-byte cap, an
unknown control-packet type — are fake-expressible at the client level:
the decoder raises ``MQTTProtocolError``, ``handle()`` catches it, and
the client transitions to FAILED with the decode error preserved in
``last_error`` (so the runner self-heals and the fault is diagnosable).

``test_decoder`` already pins these at the codec seam in isolation
(unknown type, short PUBLISH, oversized simple-ack) and ``test_packets``
pins the >4-byte varlen at ``decode_varlen``.  What was uncovered is the
*client* path: that a decoder ``MQTTProtocolError`` reaches a clean
FAILED transition instead of crashing the tick or being swallowed.  Own
file per the suite-split convention.
"""

from chumicro_mqtt import MQTTProtocolError, ProtocolState
from chumicro_mqtt._wire import PacketDecoder
from chumicro_mqtt.testing import canned_connack_bytes, drive, new_client
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks


def _connected_client(sock, ticks):
    client = new_client(sock, ticks)
    sock.enqueue_recv(canned_connack_bytes(return_code=0))
    client.connect()
    drive(client, ticks, count=2)
    assert client.state == ProtocolState.CONNECTED
    return client


class TestMalformedConnack:
    def test_bad_connack_body_length_faults_during_connect(self) -> None:
        # CONNACK 0x20 with remaining-length 3 (one byte too long): the
        # decoder rejects the body, handle() catches it, and the connect
        # fails cleanly rather than hanging awaiting a valid CONNACK.
        sock = FakeSocket()
        ticks = FakeTicks()
        sock.enqueue_recv(b"\x20\x03\x00\x00\x00")
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.FAILED
        assert isinstance(client.last_error, MQTTProtocolError)
        assert "CONNACK body must be exactly 2 bytes" in str(client.last_error)

    def test_decoder_rejects_bad_connack_body_length(self) -> None:
        # Pin the raise site itself, decoupled from the client plumbing.
        decoder = PacketDecoder()
        frame = b"\x20\x03\x00\x00\x00"
        decoder.fill_buffer()[:len(frame)] = frame
        decoder.advance(len(frame))
        with raises(MQTTProtocolError, match="CONNACK body must be exactly 2 bytes"):
            decoder.read_next()


class TestMalformedInboundWhileConnected:
    def test_oversized_remaining_length_faults(self) -> None:
        # A fixed header whose remaining-length varlen never terminates
        # within 4 bytes is malformed (not merely "need more"); the
        # decoder raises and the client faults instead of scanning forever.
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)
        # 0x30 PUBLISH + five continuation bytes: varlen overruns the cap.
        sock.enqueue_recv(b"\x30\xff\xff\xff\xff\x7f")
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED
        assert isinstance(client.last_error, MQTTProtocolError)
        assert "varlen exceeds 4 bytes" in str(client.last_error)

    def test_unknown_packet_type_faults(self) -> None:
        # A control-packet high-nibble the client doesn't implement
        # (0xF0 == MQTT 5 AUTH) is a peer/protocol bug -> FAILED.
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)
        sock.enqueue_recv(b"\xf0\x00")
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED
        assert isinstance(client.last_error, MQTTProtocolError)
        assert "unknown packet type" in str(client.last_error)
