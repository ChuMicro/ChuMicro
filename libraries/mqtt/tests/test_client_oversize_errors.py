"""mqtt client: oversize/intact tiers, not-connected guards, error
paths, decoder edge cases, suback rejection."""

from chumicro_mqtt import (
    ProtocolState,
    WhenOversized,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_publish_bytes,
    canned_suback_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks


class TestWhenOversized:
    def test_drop_with_event_fires_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks,
            rx_buffer_size=64,
            max_message_bytes=100,  # tier 3: 200-byte payload exceeds cap
            when_oversized=WhenOversized.DROP_WITH_EVENT,
        )
        client.connect()
        drive(client, ticks, count=2)

        captured: list[tuple[int, str]] = []

        def _record(reported_length: int, topic: str) -> None:
            captured.append((reported_length, topic))

        client.on_oversized = _record
        sock.enqueue_recv(canned_publish_bytes("log", b"x" * 200, qos=0))
        # Drive enough ticks for the decoder's rolling drain to complete.
        drive(client, ticks, count=10)
        assert len(captured) == 1
        assert captured[0][1] == "log"
        # Still CONNECTED.  DROP_WITH_EVENT drops the payload and
        # stays connected.
        assert client.state == ProtocolState.CONNECTED

    def test_disconnect_policy_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks,
            rx_buffer_size=64,
            max_message_bytes=100,  # tier 3 forces the policy to apply
            when_oversized=WhenOversized.DISCONNECT,
        )
        client.connect()
        drive(client, ticks, count=2)

        sock.enqueue_recv(canned_publish_bytes("log", b"x" * 200, qos=0))
        drive(client, ticks, count=10)
        assert client.state == ProtocolState.FAILED


class TestIntactTier:
    """Tier 2: PUBLISH > rx_buffer_size but ≤ max_message_bytes."""

    def test_intact_publish_delivers_full_payload(self) -> None:
        """A 1 KB payload on a 64 B rx buffer + 8 KB max routes through tier 2."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks,
            rx_buffer_size=64,        # forces tier-1 boundary low
            max_message_bytes=8192,   # tier-2 ceiling well above payload size
        )
        client.connect()
        drive(client, ticks, count=2)

        received: list[tuple[str, bytes]] = []

        def _on_message(topic: str, payload: bytes) -> None:
            received.append((topic, payload))

        client.on_message = _on_message
        big_payload = b"x" * 1024
        sock.enqueue_recv(canned_publish_bytes("data", big_payload, qos=0))
        drive(client, ticks, count=30)  # several ticks to drain across rx_buffer fills

        assert len(received) == 1
        assert received[0][0] == "data"
        assert received[0][1] == big_payload
        assert client.state == ProtocolState.CONNECTED

    def test_intact_qos1_sends_puback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks,
            rx_buffer_size=64,
            max_message_bytes=8192,
        )
        client.connect()
        drive(client, ticks, count=2)
        sock.sent = bytearray()  # reset to observe just the PUBACK

        big_payload = b"y" * 512
        sock.enqueue_recv(
            canned_publish_bytes("data", big_payload, qos=1, packet_id=4242),
        )
        drive(client, ticks, count=20)
        # PUBACK = 0x40 0x02 packet_id_hi packet_id_lo.  4242 = 0x1092.
        assert b"\x40\x02\x10\x92" in bytes(sock.sent)


class TestNotConnectedGuards:
    def test_publish_before_connect_raises(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        with raises(Exception):  # noqa: B017
            client.publish("x", b"y")

    def test_subscribe_before_connect_raises(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        with raises(Exception):  # noqa: B017
            client.subscribe("x")

    def test_unsubscribe_before_connect_raises(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        with raises(Exception):  # noqa: B017
            client.unsubscribe("x")


class TestDecoderEdgeCases:
    def test_oversized_disconnect_policy_raises_protocol_error(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks,
            rx_buffer_size=64,
            max_message_bytes=100,  # tier 3 forces DISCONNECT
            when_oversized=WhenOversized.DISCONNECT,
        )
        client.connect()
        drive(client, ticks, count=2)
        sock.enqueue_recv(canned_publish_bytes("topic", b"x" * 200, qos=0))
        drive(client, ticks, count=10)
        assert client.state == ProtocolState.FAILED

    def test_oversized_drop_silent_does_not_fire_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks,
            rx_buffer_size=64,
            max_message_bytes=100,  # tier 3 forces the silent-drop path
            when_oversized=WhenOversized.DROP_SILENT,
        )
        client.connect()
        drive(client, ticks, count=2)
        captured: list[object] = []

        def _record(reported_length: int, topic: str) -> None:
            captured.append((reported_length, topic))

        client.on_oversized = _record
        sock.enqueue_recv(canned_publish_bytes("topic", b"x" * 200, qos=0))
        drive(client, ticks, count=10)
        assert captured == []
        assert client.state == ProtocolState.CONNECTED  # silent drop, still connected

    def test_oversize_topic_with_drop_with_event_emits_none_topic(self) -> None:
        """A topic larger than rx_buffer_size fires on_oversized with topic=None."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        # Tiny rx buffer so a normal-length topic blows the prelude.
        # max_message_bytes low so the rest also routes through tier 3.
        client = new_client(
            sock, ticks,
            rx_buffer_size=16,
            max_message_bytes=32,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
        )
        client.connect()
        drive(client, ticks, count=2)

        captured: list[tuple[int, object]] = []

        def _record(reported_length: int, topic) -> None:
            captured.append((reported_length, topic))

        client.on_oversized = _record
        # 50-byte topic: much bigger than the 16-byte rx buffer.
        long_topic = "a" * 50
        sock.enqueue_recv(canned_publish_bytes(long_topic, b"small", qos=0))
        drive(client, ticks, count=20)
        assert len(captured) == 1
        assert captured[0][1] is None  # topic unparseable
        assert client.state == ProtocolState.CONNECTED


class TestSubackRejection:
    def test_suback_with_0x80_byte_marks_failed(self) -> None:
        """granted_qos == 0x80 means the broker rejected the subscription."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        client.subscribe("forbidden")
        drive(client, ticks, count=1)
        # Broker rejects with 0x80.  packet_id == 1 (first allocation).
        sock.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=0x80))
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.FAILED
