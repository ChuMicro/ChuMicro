"""mqtt client: oversize tier, when_disconnected policy, error
paths, decoder edge cases, suback rejection."""

from chumicro_mqtt import (
    MQTTBackpressureError,
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
            rx_buffer_size=64,  # 200-byte payload overflows the steady buffer
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
            rx_buffer_size=64,  # 200-byte payload overflows the steady buffer
            when_oversized=WhenOversized.DISCONNECT,
        )
        client.connect()
        drive(client, ticks, count=2)

        sock.enqueue_recv(canned_publish_bytes("log", b"x" * 200, qos=0))
        drive(client, ticks, count=10)
        assert client.state == ProtocolState.FAILED


class TestNotConnectedGuards:
    def test_publish_before_connect_raises_under_raise_policy(self) -> None:
        """``when_disconnected="raise"`` keeps the pre-queue publish guard."""
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks, when_disconnected="raise")
        with raises(Exception):  # noqa: B017
            client.publish("x", b"y")

    def test_publish_before_connect_queues_and_drains_on_connack(self) -> None:
        """Default ``when_disconnected="queue"`` buffers, then flushes on CONNACK."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)  # default policy: queue
        # Queued while DISCONNECTED — no raise, nothing on the wire yet.
        client.publish("early", b"payload", qos=0)
        assert client.state == ProtocolState.DISCONNECTED
        assert b"early" not in bytes(sock.sent)
        # Connect: the CONNACK drain flushes the queued publish.
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        assert b"early" in bytes(sock.sent)

    def test_publish_queue_full_raises_backpressure(self) -> None:
        """A full pre-connect queue under "queue" raises the backpressure error."""
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks, pre_connect_queue_size=2)
        client.publish("a", b"1", qos=0)
        client.publish("b", b"2", qos=0)
        with raises(MQTTBackpressureError):
            client.publish("c", b"3", qos=0)

    def test_unknown_when_disconnected_policy_rejected(self) -> None:
        """Only the two-policy set (queue / raise) constructs."""
        sock = FakeSocket()
        ticks = FakeTicks()
        try:
            new_client(sock, ticks, when_disconnected="drop_oldest")
        except ValueError as error:
            assert "when_disconnected" in str(error)
        else:
            raise AssertionError("expected ValueError for a retired policy")

    def test_subscribe_before_connect_declares_without_raising(self) -> None:
        """subscribe() pre-connect is a declaration: no raise, no wire traffic yet."""
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.subscribe("x", qos=1)  # accepted while DISCONNECTED
        assert client.state == ProtocolState.DISCONNECTED
        assert bytes(sock.sent) == b""  # nothing on the wire yet
        assert "x" in client._subscriptions  # recorded in the desired-set

    def test_unsubscribe_before_connect_retracts_without_raising(self) -> None:
        """unsubscribe() pre-connect retracts a declaration: no raise, no wire traffic."""
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.subscribe("x", qos=1)
        client.unsubscribe("x")  # accepted while DISCONNECTED
        assert client.state == ProtocolState.DISCONNECTED
        assert bytes(sock.sent) == b""
        assert "x" not in client._subscriptions


class TestDecoderEdgeCases:
    def test_oversized_disconnect_policy_raises_protocol_error(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks,
            rx_buffer_size=64,  # 200-byte payload overflows the steady buffer
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
            rx_buffer_size=64,  # 200-byte payload overflows the steady buffer
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
        # Tiny rx buffer so a normal-length topic blows the prelude and
        # routes through the oversized tier.
        client = new_client(
            sock, ticks,
            rx_buffer_size=16,
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
