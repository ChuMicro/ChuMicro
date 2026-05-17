"""mqtt client: inbound publish, topic-prefix sugar, MQTTPublisher,
last-will prefix, keepalive."""

from chumicro_mqtt import (
    MQTTClient,
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_pingresp_bytes,
    canned_publish_bytes,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks


def _new_client(sock: FakeSocket, ticks: FakeTicks, **overrides) -> MQTTClient:
    """Build a client with FakeTicks injected."""
    kwargs = {
        "client_id": "test-client",
        "keep_alive_seconds": 60,
        "ack_timeout_seconds": 5.0,
        "publish_retry_max": 2,
        "ticks": ticks,
    }
    kwargs.update(overrides)
    return MQTTClient(sock, **kwargs)

def _drive(client: MQTTClient, ticks: FakeTicks, count: int = 1) -> None:
    """Run *count* tick iterations of the client."""
    for _ in range(count):
        now = ticks.ticks_ms()
        client.handle(now)


class TestInboundPublish:
    def test_on_message_fires(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        captured: list[tuple[str, bytes]] = []
        client.on_message = lambda topic, payload: captured.append((topic, payload))
        sock.enqueue_recv(canned_publish_bytes("temp", b"99", qos=0))
        _drive(client, ticks, count=1)
        assert captured == [("temp", b"99")]

    def test_qos1_publish_triggers_puback_send(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)
        sock.sent = bytearray()  # MP bytearray lacks .clear()

        sock.enqueue_recv(canned_publish_bytes("temp", b"99", qos=1, packet_id=42))
        _drive(client, ticks, count=2)

        # PUBACK 42 should be on the wire.
        assert b"\x40\x02\x00\x2a" in bytes(sock.sent)

    def test_pattern_handlers_fire(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        captured: list[str] = []
        client.add_pattern_handler(
            "sensors/+/temperature",
            lambda topic, payload: captured.append(topic),
        )
        sock.enqueue_recv(canned_publish_bytes("sensors/back-porch/temperature", b"21", qos=0))
        sock.enqueue_recv(canned_publish_bytes("other/topic", b"x", qos=0))
        _drive(client, ticks, count=1)
        assert captured == ["sensors/back-porch/temperature"]

    def test_remove_pattern_handler_by_handler_only(self) -> None:
        """``remove_pattern_handler(handler)`` strips every registration of *handler*."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        fires: list[str] = []
        def handler(topic, _payload):
            fires.append(topic)

        client.add_pattern_handler("a/+", handler)
        client.add_pattern_handler("b/#", handler)
        client.remove_pattern_handler(handler)

        sock.enqueue_recv(canned_publish_bytes("a/x", b"", qos=0))
        sock.enqueue_recv(canned_publish_bytes("b/y/z", b"", qos=0))
        _drive(client, ticks, count=1)
        assert fires == []

    def test_remove_pattern_handler_by_handler_and_pattern(self) -> None:
        """``remove_pattern_handler(handler, pattern=...)`` removes one registration."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        fires: list[str] = []
        def handler(topic, _payload):
            fires.append(topic)

        client.add_pattern_handler("a/+", handler)
        client.add_pattern_handler("b/#", handler)
        client.remove_pattern_handler(handler, pattern="a/+")

        sock.enqueue_recv(canned_publish_bytes("a/x", b"", qos=0))
        sock.enqueue_recv(canned_publish_bytes("b/y/z", b"", qos=0))
        _drive(client, ticks, count=1)
        # Only the b/# registration survived.
        assert fires == ["b/y/z"]


class TestTopicPrefixSugar:
    def test_publish_prefixes_with_root_topic_and_client_id(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(
            sock, ticks,
            client_id="mainLightSwitch",
            root_topic="livingRoom",
        )
        client.connect()
        _drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.publish("switchState", b"on", qos=0)
        _drive(client, ticks, count=1)
        assert b"livingRoom/mainLightSwitch/switchState" in bytes(sock.sent)

    def test_publish_without_root_topic_is_verbatim(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)  # default root_topic=None
        client.connect()
        _drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.publish("temp", b"42", qos=0)
        _drive(client, ticks, count=1)
        wire = bytes(sock.sent)
        assert b"temp" in wire
        # No prefix was injected.
        assert b"test-client/temp" not in wire

    def test_publish_raw_bypasses_prefix(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(
            sock, ticks,
            client_id="mainLightSwitch",
            root_topic="livingRoom",
        )
        client.connect()
        _drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.publish_raw("$SYS/bridge/status", b"online", qos=0)
        _drive(client, ticks, count=1)
        wire = bytes(sock.sent)
        assert b"$SYS/bridge/status" in wire
        assert b"livingRoom" not in wire

    def test_subscribe_prefixes_topic(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(
            sock, ticks,
            client_id="thing-42",
            root_topic="myapp",
        )
        client.connect()
        _drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.subscribe("commands/+")
        _drive(client, ticks, count=1)
        assert b"myapp/thing-42/commands/+" in bytes(sock.sent)

    def test_subscribe_raw_bypasses_prefix(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(
            sock, ticks,
            client_id="thing-42",
            root_topic="myapp",
        )
        client.connect()
        _drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.subscribe_raw("$SYS/broker/uptime")
        _drive(client, ticks, count=1)
        wire = bytes(sock.sent)
        assert b"$SYS/broker/uptime" in wire
        assert b"myapp" not in wire

    def test_unsubscribe_prefixes_topic(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(
            sock, ticks,
            client_id="thing-42",
            root_topic="myapp",
        )
        client.connect()
        _drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.unsubscribe("commands/+")
        _drive(client, ticks, count=1)
        assert b"myapp/thing-42/commands/+" in bytes(sock.sent)


class TestMQTTPublisher:
    def test_publisher_publishes_under_bound_topic(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)
        sock.sent = bytearray()
        pub = client.publisher("temperature", qos=0)
        pub.publish(b"21")
        _drive(client, ticks, count=1)
        wire = bytes(sock.sent)
        assert b"temperature" in wire
        assert wire.endswith(b"21")

    def test_publisher_respects_root_topic_prefix(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(
            sock, ticks,
            client_id="mainLightSwitch",
            root_topic="livingRoom",
        )
        client.connect()
        _drive(client, ticks, count=2)
        sock.sent = bytearray()
        pub = client.publisher("switchState", qos=0)
        pub.publish("on")  # str auto-encoded
        _drive(client, ticks, count=1)
        wire = bytes(sock.sent)
        assert b"livingRoom/mainLightSwitch/switchState" in wire
        assert wire.endswith(b"on")


class TestLastWillPrefix:
    def test_will_topic_is_prefixed_in_connect_packet(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = MQTTClient(
            sock,
            client_id="mainLightSwitch",
            root_topic="livingRoom",
            will_topic="online",
            will_message=b"false",
            ticks=ticks,
        )
        client.connect()
        _drive(client, ticks, count=1)
        # CONNECT packet starts with 0x10.  Look for the prefixed will topic.
        wire = bytes(sock.sent)
        assert b"livingRoom/mainLightSwitch/online" in wire

    def test_will_topic_raw_skips_prefix(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = MQTTClient(
            sock,
            client_id="mainLightSwitch",
            root_topic="livingRoom",
            will_topic_raw="$SYS/bridge/dead",
            will_message=b"true",
            ticks=ticks,
        )
        client.connect()
        _drive(client, ticks, count=1)
        wire = bytes(sock.sent)
        assert b"$SYS/bridge/dead" in wire
        # Prefix should NOT have been applied.
        assert b"livingRoom/mainLightSwitch/$SYS" not in wire

    def test_will_topic_and_will_topic_raw_mutually_exclusive(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        with raises(ValueError):
            MQTTClient(
                sock,
                client_id="thing",
                will_topic="online",
                will_topic_raw="$SYS/x",
                ticks=ticks,
            )


class TestKeepalive:
    def test_pingreq_sent_at_half_interval(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks, keep_alive_seconds=30)
        client.connect()
        _drive(client, ticks, count=2)
        sock.sent = bytearray()  # MP bytearray lacks .clear()

        # Just past the 15-second mark — half of keepalive.
        ticks.advance(15_500)
        _drive(client, ticks, count=1)
        assert b"\xc0\x00" in bytes(sock.sent)  # PINGREQ wire bytes

    def test_pingresp_clears_pending(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks, keep_alive_seconds=30)
        client.connect()
        _drive(client, ticks, count=2)
        ticks.advance(15_500)
        _drive(client, ticks, count=1)
        sock.enqueue_recv(canned_pingresp_bytes())
        _drive(client, ticks, count=1)
        # PINGRESP arriving means the pending entry got cleared and
        # a PINGRESP timeout doesn't trip.
        assert client.state == ProtocolState.CONNECTED
