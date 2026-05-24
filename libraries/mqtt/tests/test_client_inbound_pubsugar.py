"""mqtt client: inbound publish, topic-prefix sugar, last-will
prefix, keepalive."""

from chumicro_mqtt import (
    MQTTClient,
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

    def test_pattern_handlers_fire(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        captured: list[str] = []
        client.add_pattern_handler(
            "sensors/+/temperature",
            lambda topic, payload: captured.append(topic),
        )
        sock.enqueue_recv(canned_publish_bytes("sensors/back-porch/temperature", b"21", qos=0))
        sock.enqueue_recv(canned_publish_bytes("other/topic", b"x", qos=0))
        drive(client, ticks, count=1)
        assert captured == ["sensors/back-porch/temperature"]

    def test_remove_pattern_handler_by_handler_only(self) -> None:
        """``remove_pattern_handler(handler)`` strips every registration of *handler*."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        fires: list[str] = []
        def handler(topic, _payload):
            fires.append(topic)

        client.add_pattern_handler("a/+", handler)
        client.add_pattern_handler("b/#", handler)
        client.remove_pattern_handler(handler)

        sock.enqueue_recv(canned_publish_bytes("a/x", b"", qos=0))
        sock.enqueue_recv(canned_publish_bytes("b/y/z", b"", qos=0))
        drive(client, ticks, count=1)
        assert fires == []

    def test_remove_pattern_handler_by_handler_and_pattern(self) -> None:
        """``remove_pattern_handler(handler, pattern=...)`` removes one registration."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        fires: list[str] = []
        def handler(topic, _payload):
            fires.append(topic)

        client.add_pattern_handler("a/+", handler)
        client.add_pattern_handler("b/#", handler)
        client.remove_pattern_handler(handler, pattern="a/+")

        sock.enqueue_recv(canned_publish_bytes("a/x", b"", qos=0))
        sock.enqueue_recv(canned_publish_bytes("b/y/z", b"", qos=0))
        # One recv per tick: two FakeSocket chunks need two ticks to drain.
        drive(client, ticks, count=2)
        # Only the b/# registration survived.
        assert fires == ["b/y/z"]


class TestTopicPrefixSugar:
    def test_publish_prefixes_with_root_topic_and_client_id(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks,
            client_id="mainLightSwitch",
            root_topic="livingRoom",
        )
        client.connect()
        drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.publish("switchState", b"on", qos=0)
        drive(client, ticks, count=1)
        assert b"livingRoom/mainLightSwitch/switchState" in bytes(sock.sent)

    def test_publish_without_root_topic_is_verbatim(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)  # default root_topic=None
        client.connect()
        drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.publish("temp", b"42", qos=0)
        drive(client, ticks, count=1)
        wire = bytes(sock.sent)
        assert b"temp" in wire
        # No prefix was injected.
        assert b"test-client/temp" not in wire

    def test_publish_prefixed_false_bypasses_prefix(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks,
            client_id="mainLightSwitch",
            root_topic="livingRoom",
        )
        client.connect()
        drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.publish("$SYS/bridge/status", b"online", qos=0, prefixed=False)
        drive(client, ticks, count=1)
        wire = bytes(sock.sent)
        assert b"$SYS/bridge/status" in wire
        assert b"livingRoom" not in wire

    def test_subscribe_prefixes_topic(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks,
            client_id="thing-42",
            root_topic="myapp",
        )
        client.connect()
        drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.subscribe("commands/+")
        drive(client, ticks, count=1)
        assert b"myapp/thing-42/commands/+" in bytes(sock.sent)

    def test_subscribe_prefixed_false_bypasses_prefix(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks,
            client_id="thing-42",
            root_topic="myapp",
        )
        client.connect()
        drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.subscribe("$SYS/broker/uptime", prefixed=False)
        drive(client, ticks, count=1)
        wire = bytes(sock.sent)
        assert b"$SYS/broker/uptime" in wire
        assert b"myapp" not in wire

    def test_unsubscribe_prefixes_topic(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks,
            client_id="thing-42",
            root_topic="myapp",
        )
        client.connect()
        drive(client, ticks, count=2)
        sock.sent = bytearray()
        client.unsubscribe("commands/+")
        drive(client, ticks, count=1)
        assert b"myapp/thing-42/commands/+" in bytes(sock.sent)


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
        drive(client, ticks, count=1)
        # CONNECT packet starts with 0x10.  Look for the prefixed will topic.
        wire = bytes(sock.sent)
        assert b"livingRoom/mainLightSwitch/online" in wire

    def test_will_prefixed_false_skips_prefix(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = MQTTClient(
            sock,
            client_id="mainLightSwitch",
            root_topic="livingRoom",
            will_topic="$SYS/bridge/dead",
            will_prefixed=False,
            will_message=b"true",
            ticks=ticks,
        )
        client.connect()
        drive(client, ticks, count=1)
        wire = bytes(sock.sent)
        assert b"$SYS/bridge/dead" in wire
        # Prefix should NOT have been applied.
        assert b"livingRoom/mainLightSwitch/$SYS" not in wire


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
