"""mqtt client: unexpected acks + tx-queue backpressure.

The bounded-recv-per-tick tests live in ``test_client_bounded_recv.py``
(split so each file fits the unix-lane heap budget)."""

from chumicro_mqtt import (
    MQTTBackpressureError,
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_pingresp_bytes,
    canned_puback_bytes,
    canned_publish_bytes,
    canned_suback_bytes,
    canned_unsuback_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks


class TestUnexpectedAcks:
    def test_unmatched_puback_is_tolerated(self) -> None:
        # A PUBACK with no matching in-flight entry is tolerated (like
        # PINGRESP), not faulted: the common cause is a duplicate PUBACK
        # from the broker acking both an original publish and the retry
        # path's DUP retransmit after a slow-but-not-lost first ack, so
        # faulting would tear down the session the retry protects.
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        sock.enqueue_recv(canned_puback_bytes(packet_id=999))
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.CONNECTED

    def test_unexpected_suback_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        sock.enqueue_recv(canned_suback_bytes(packet_id=999, granted_qos=0))
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED

    def test_unexpected_unsuback_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        sock.enqueue_recv(canned_unsuback_bytes(packet_id=999))
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED

    def test_unexpected_pingresp_silently_tolerated(self) -> None:
        """PINGRESP with no pending tracker keeps the connection alive.

        Reason: PINGREQ timeout fires (clearing the tracker), the
        broker's PINGRESP arrives a tick later, and re-faulting through
        a healthy connection would be a false positive.
        """
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        # PINGRESP with no pending tracker.
        sock.enqueue_recv(canned_pingresp_bytes())
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.CONNECTED


class TestTxQueueBackpressure:
    """User-initiated publishes raise ``MQTTBackpressureError`` past the cap."""

    def test_default_cap_is_20_packets(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)  # default cap
        assert client._max_tx_queue_size == 20  # noqa: SLF001 - pin the default

    def test_publish_raises_when_cap_exceeded(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks, max_tx_queue_size=3)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        # Queue is empty post-CONNECT.  Three publishes fill it.  The
        # fourth should raise.  Don't drive between publishes so the
        # queue actually accumulates.
        client.publish("topic/a", b"one", qos=0)
        client.publish("topic/a", b"two", qos=0)
        client.publish("topic/a", b"three", qos=0)
        with raises(MQTTBackpressureError, match="tx queue full"):
            client.publish("topic/a", b"four", qos=0)

    def test_callback_qos0_publish_reserves_two_slots(self) -> None:
        # A callback-bearing QoS-0 publish enqueues a packet plus a
        # marker (both pinning the payload), so it needs two free slots
        # and is capacity-checked as one unit, not one item at a time.
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks, max_tx_queue_size=3)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        fired = []
        client.publish(
            "t", b"one", qos=0,
            on_publish=lambda topic, payload: fired.append(1),
        )
        assert len(client._tx_queue) == 2  # packet + marker  # noqa: SLF001

        # Only one slot is free (3 - 2); a second callback-publish needs
        # two and must raise without half-landing its packet.
        with raises(MQTTBackpressureError, match="tx queue full"):
            client.publish(
                "t", b"two", qos=0,
                on_publish=lambda topic, payload: fired.append(2),
            )
        assert len(client._tx_queue) == 2  # atomic, packet not added  # noqa: SLF001

    def test_qos1_publish_rolls_back_packet_id_on_backpressure(self) -> None:
        """If the user-tx enqueue trips the cap, the in-flight allocation
        must be rolled back so the packet_id pool isn't leaked."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks, max_tx_queue_size=1)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        # First QoS 1 publish fills the cap.
        client.publish("topic/a", b"one", qos=1)
        in_flight_after_first = list(client._in_flight.values())  # noqa: SLF001
        assert len(in_flight_after_first) == 1

        # Second publish overflows.  Expect the packet_id allocation to
        # be discarded along with the raise.
        with raises(MQTTBackpressureError):
            client.publish("topic/a", b"two", qos=1)
        in_flight_after_failed = list(client._in_flight.values())  # noqa: SLF001
        assert len(in_flight_after_failed) == 1  # rolled back, not leaked
        assert in_flight_after_failed[0].packet_id == in_flight_after_first[0].packet_id

    def test_protocol_internal_traffic_bypasses_cap(self) -> None:
        """PUBACK responses on inbound QoS 1 PUBLISHes are protocol
        bookkeeping.  They must enqueue even if the user TX queue is
        full, otherwise QoS 1 contract breaks."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks, max_tx_queue_size=1)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        # Fill the user cap.
        client.publish("topic/a", b"user-pub", qos=0)

        # Now an inbound QoS 1 PUBLISH from the broker.  Handler must
        # enqueue the PUBACK even though the user-cap is full.
        sock.enqueue_recv(canned_publish_bytes(
            "topic/in", b"hi from broker", qos=1, packet_id=42,
        ))
        # No exception: internal enqueue bypasses the cap.
        client.handle(ticks.ticks_ms())
