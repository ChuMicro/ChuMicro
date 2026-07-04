"""mqtt client: QoS 0/1 publish and subscribe/unsubscribe."""


from chumicro_mqtt import (
    UnsupportedQoSError,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_puback_bytes,
    canned_suback_bytes,
    canned_unsuback_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks


class TestPublishQos0:
    def test_qos0_writes_packet_immediately(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        sock.sent = bytearray()  # MP bytearray lacks .clear()
        client.publish("temp", b"42", qos=0)
        drive(client, ticks, count=1)
        # First byte 0x30 = PUBLISH qos 0.
        assert sock.sent[0] == 0x30
        assert b"temp" in bytes(sock.sent)
        assert bytes(sock.sent).endswith(b"42")

    def test_qos0_callback_fires_after_send(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        captured: list[tuple[str, bytes]] = []

        def capture(topic: str, payload: bytes) -> None:
            captured.append((topic, payload))

        client.publish("temp", b"42", qos=0, on_publish=capture)
        drive(client, ticks, count=1)
        assert captured == [("temp", b"42")]

    def test_qos0_fires_global_on_publish_without_per_call_callback(self) -> None:
        """Global ``client.on_publish`` fires for QoS 0 sends.

        Matches the QoS 1 behavior so a user who sets the global
        callback once (rather than passing ``on_publish=`` on every
        call) sees every send.
        """
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        captured: list[tuple[str, bytes]] = []
        client.on_publish = lambda topic, payload: captured.append((topic, payload))
        client.publish("temp", b"42", qos=0)
        drive(client, ticks, count=1)
        assert captured == [("temp", b"42")]


class TestPublishQos1:
    def test_qos1_publish_then_puback_fires_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        captured: list[tuple[str, bytes]] = []

        def _capture(topic: str, payload: bytes) -> None:
            captured.append((topic, payload))

        client.publish("temp", b"42", qos=1, on_publish=_capture)

        # After tick 3: PUBLISH on the wire.
        drive(client, ticks, count=1)
        # The packet_id allocated should be the next free (1: the
        # SUBACK/PUBACK pool is shared but no subs queued yet).
        assert b"temp" in bytes(sock.sent)
        # Now broker sends PUBACK.
        sock.enqueue_recv(canned_puback_bytes(packet_id=1))
        drive(client, ticks, count=1)
        assert captured == [("temp", b"42")]

    def test_concurrent_qos1_publishes_dispatch_independently(self) -> None:
        """Two QoS 1 publishes at once both get their callbacks on PUBACK."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        first_called: list[bool] = []
        second_called: list[bool] = []
        client.publish(
            "first",
            b"1",
            qos=1,
            on_publish=lambda topic, payload: first_called.append(True),
        )
        client.publish(
            "second",
            b"2",
            qos=1,
            on_publish=lambda topic, payload: second_called.append(True),
        )
        # One send per tick: two queued PUBLISHes need two ticks.
        drive(client, ticks, count=2)  # Send both.

        # Broker pubacks them out of order.
        sock.enqueue_recv(canned_puback_bytes(packet_id=2))
        sock.enqueue_recv(canned_puback_bytes(packet_id=1))
        # One recv per tick: two FakeSocket PUBACK chunks need two ticks.
        drive(client, ticks, count=2)

        assert first_called == [True]
        assert second_called == [True]

    def test_qos1_retries_on_ack_timeout(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        sock.sent = bytearray()  # MP bytearray lacks .clear()
        client.publish("temp", b"42", qos=1)
        drive(client, ticks, count=1)
        first_send_length = len(sock.sent)
        # Skip past the ack timeout.  No PUBACK arrives.
        ticks.advance(10_000)
        drive(client, ticks, count=1)
        # Retry packet should now be on the wire (DUP flag set).
        assert len(sock.sent) > first_send_length
        retry_byte = sock.sent[first_send_length]
        assert retry_byte & 0x08  # DUP bit set on the retry

    def test_qos1_retransmit_caches_dup_packet_across_retries(self) -> None:
        # The DUP-flagged retransmit is built once and reused, not
        # re-copied from packet_bytes on every ack-timeout expiry.
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        client.publish("temp", b"42", qos=1)
        drive(client, ticks, count=1)
        entry = next(iter(client._in_flight.values()))  # noqa: SLF001
        assert entry.dup_packet_bytes is None  # not built until first retry

        ticks.advance(10_000)
        drive(client, ticks, count=1)
        first_dup = entry.dup_packet_bytes
        assert first_dup is not None
        assert first_dup[0] & 0x08  # DUP bit set

        ticks.advance(10_000)
        drive(client, ticks, count=1)
        # Same object reused on the second retry, not re-copied.
        assert entry.dup_packet_bytes is first_dup

    def test_qos1_publish_qos2_raises(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        with raises(UnsupportedQoSError):
            client.publish("topic", b"x", qos=2)


class TestSubscribe:
    def test_subscribe_then_suback_fires_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        captured: list[list[int]] = []
        client.subscribe(
            "sensors/+",
            qos=1,
            on_subscribe=lambda topic, granted: captured.append(granted),
        )
        drive(client, ticks, count=1)
        sock.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=1))
        drive(client, ticks, count=1)
        assert captured == [[1]]

    def test_unsubscribe_then_unsuback_fires_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        captured: list[bool] = []
        client.unsubscribe(
            "sensors/+",
            on_unsubscribe=lambda topic: captured.append(True),
        )
        drive(client, ticks, count=1)
        sock.enqueue_recv(canned_unsuback_bytes(packet_id=1))
        drive(client, ticks, count=1)
        assert captured == [True]
