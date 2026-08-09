"""mqtt client: inbound publish, verbatim topics, keepalive."""

from chumicro_mqtt import (
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_pingresp_bytes,
    canned_publish_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


class TestInboundPublish:
    def test_on_message_fires(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        captured: list[tuple[str, bytes]] = []
        client.on_message = lambda topic, payload: captured.append((topic, payload))
        sock.enqueue_recv(canned_publish_bytes("temp", b"99", qos=0))
        drive(client, ticks, count=1)
        assert captured == [("temp", b"99")]

    def test_qos1_publish_triggers_puback_send(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        sock.sent = bytearray()  # MP bytearray lacks .clear()

        sock.enqueue_recv(canned_publish_bytes("temp", b"99", qos=1, packet_id=42))
        drive(client, ticks, count=2)

        # PUBACK 42 should be on the wire.
        assert b"\x40\x02\x00\x2a" in bytes(sock.sent)


class TestVerbatimTopics:
    def test_publish_topic_goes_on_wire_as_written(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.publish("$SYS/bridge/status", b"online", qos=0)
        drive(client, ticks, count=1)
        wire = bytes(sock.sent)
        assert b"$SYS/bridge/status" in wire
        # No per-device prefix is injected — what you publish is what
        # the broker sees.
        assert b"test-client/$SYS" not in wire

    def test_subscribe_topic_goes_on_wire_as_written(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.subscribe("commands/+")
        drive(client, ticks, count=1)
        wire = bytes(sock.sent)
        assert b"commands/+" in wire
        assert b"test-client/commands" not in wire


class TestKeepalive:
    def test_pingreq_sent_at_half_interval(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks, keep_alive_seconds=30)
        client.connect()
        drive(client, ticks, count=2)
        sock.sent = bytearray()  # MP bytearray lacks .clear()

        # Just past the 15-second mark (half of keepalive).
        ticks.advance(15_500)
        drive(client, ticks, count=1)
        assert b"\xc0\x00" in bytes(sock.sent)  # PINGREQ wire bytes

    def test_pingresp_clears_pending(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks, keep_alive_seconds=30)
        client.connect()
        drive(client, ticks, count=2)
        ticks.advance(15_500)
        drive(client, ticks, count=1)
        sock.enqueue_recv(canned_pingresp_bytes())
        drive(client, ticks, count=1)
        # PINGRESP arriving means the pending entry got cleared and
        # a PINGRESP timeout doesn't trip.
        assert client.state == ProtocolState.CONNECTED
