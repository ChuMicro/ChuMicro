"""Regression tests for the 2026-07 audit fixes on MQTTClient.

Covers: oversize-topic QoS-1 PUBACK not crashing, PUBACK receipt
order, subscription replay past the user cap, tx-headroom overflow,
partial-send writability, disconnect-from-callback, keepalive
disabled, disconnect/reconnect, and the from_config type guard.
"""

from chumicro_mqtt import (
    MQTTClient,
    ProtocolState,
)
from chumicro_mqtt._wire import PACKET_PINGREQ
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_publish_bytes,
    drive,
    new_client,
)
from chumicro_runner import IO_READ, IO_WRITE
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks

_PUBACK_PREFIX = b"\x40\x02"


def _puback(packet_id):
    return _PUBACK_PREFIX + bytes((packet_id >> 8, packet_id & 0xFF))


def _connected_client(sock, ticks, **overrides):
    """Build a socket-only client and drive it to CONNECTED."""
    client = new_client(sock, ticks, **overrides)
    sock.enqueue_recv(canned_connack_bytes(return_code=0))
    client.connect()
    drive(client, ticks, count=2)
    assert client.state == ProtocolState.CONNECTED
    return client


def _factory(*socks):
    iterator = iter(socks)

    def factory():
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=next(iterator))

    return factory


class TestPubackOrderingAndOversize:
    def test_pubacks_sent_in_receipt_order(self):
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)
        sock.sent = bytearray()  # drop CONNECT so only PUBACKs remain
        # Two QoS-1 publishes in one recv chunk.
        sock.enqueue_recv(
            canned_publish_bytes("a", b"x", qos=1, packet_id=1)
            + canned_publish_bytes("b", b"y", qos=1, packet_id=2),
        )
        drive(client, ticks, count=4)
        sent = bytes(sock.sent)
        assert _puback(1) in sent
        assert _puback(2) in sent
        assert sent.index(_puback(1)) < sent.index(_puback(2))

    def test_qos1_oversize_topic_does_not_crash(self):
        # An oversize topic prelude yields packet_id=None; the client
        # must skip the PUBACK rather than crash encoding puback(None).
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks, rx_buffer_size=16)
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        client.connect()
        drive(client, ticks, count=2)
        sock.enqueue_recv(canned_publish_bytes("a" * 50, b"x", qos=1, packet_id=7))
        drive(client, ticks, count=3)  # must not raise struct.error
        assert client.state == ProtocolState.CONNECTED


class TestReplayAndOverflow:
    def test_replay_of_many_subscriptions_does_not_fault(self):
        # 21 subscriptions against a cap of 20 must replay through the
        # headroom on reconnect, not raise backpressure -> FAILED loop.
        sock1 = FakeSocket()
        sock2 = FakeSocket()
        ticks = FakeTicks()
        client = MQTTClient(
            transport_factory=_factory(sock1, sock2),
            ticks=ticks,
            client_id="test-client",
            max_tx_queue_size=20,
        )
        sock1.enqueue_recv(canned_connack_bytes(return_code=0))
        client.connect()
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED
        for index in range(21):
            client.subscribe(f"topic/{index}", qos=0)
            drive(client, ticks, count=1)
        # Force a reconnect: the CONNACK on sock2 triggers replay of all 21.
        client.state = ProtocolState.FAILED
        sock2.enqueue_recv(canned_connack_bytes(return_code=0))
        drive(client, ticks, count=6)
        # Replay must not have crashed or re-entered FAILED forever.
        assert client.state in (ProtocolState.CONNECTED, ProtocolState.AWAITING_TRANSPORT)

    def test_puback_flood_cycles_without_reaching_the_hard_cap(self):
        # Many inbound QoS-1 publishes per tick used to outrun the
        # one-PUBACK-per-tick drain and trip the hard-cap guard.  With
        # the coalesced per-tick PUBACK batch (sent outside the packet
        # budget) the flood cycles smoothly: every publish is acked,
        # the client stays CONNECTED, and the guard is never reached.
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks, max_tx_queue_size=4)
        sock.sent = bytearray()  # count only PUBACKs from here on
        chunk = b"".join(
            canned_publish_bytes("t", b"x", qos=1, packet_id=(index % 60) + 1)
            for index in range(120)
        )
        sock.enqueue_recv(chunk)
        drive(client, ticks, count=8)
        assert client.state == ProtocolState.CONNECTED
        sent = bytes(sock.sent)
        # Nothing but the 120 four-byte PUBACKs went out, one per
        # inbound publish.
        assert len(sent) == 120 * 4
        for packet_id in range(1, 61):
            assert _puback(packet_id) in sent


class TestWritabilityAndCallbacks:
    def test_io_interest_write_only_during_partial_send(self):
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)
        client._partial_send = (memoryview(b"partial"), 0)
        # Even with an empty queue, a partial send needs writability.
        while client._tx_queue:
            client._tx_queue.popleft()
        # The partial send wants write; read interest drops while the
        # recv is suppressed for outbound backpressure (the socket
        # isn't taking our bytes, so we stop taking the broker's).
        assert client.io_interest(ticks.ticks_ms()) == IO_WRITE
        # Once the partial send lands, read interest returns.
        client._partial_send = None
        assert client.io_interest(ticks.ticks_ms()) == IO_READ

    def test_disconnect_from_on_message_lands_disconnected(self):
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)

        def on_message(topic, payload):
            client.disconnect()

        client.on_message = on_message
        sock.enqueue_recv(canned_publish_bytes("a", b"x", qos=1, packet_id=1))
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.DISCONNECTED


class TestKeepaliveAndReconnect:
    def test_keepalive_zero_sends_no_pingreq(self):
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks, keep_alive_seconds=0)
        sock.sent = bytearray()
        for _ in range(10):
            ticks.advance(1000)
            drive(client, ticks, count=1)
        # keep_alive_seconds=0 disables keepalive: no PINGREQ ever queued.
        assert PACKET_PINGREQ not in bytes(sock.sent)
        assert len(client._tx_queue) == 0

    def test_disconnect_then_connect_via_factory_succeeds(self):
        sock1 = FakeSocket()
        sock2 = FakeSocket()
        ticks = FakeTicks()
        client = MQTTClient(
            transport_factory=_factory(sock1, sock2),
            ticks=ticks,
            client_id="test-client",
        )
        sock1.enqueue_recv(canned_connack_bytes(return_code=0))
        client.connect()
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED
        client.disconnect()
        assert client.state == ProtocolState.DISCONNECTED
        # A fresh connect must route through the factory (sock2), not
        # re-arm CONNECT against the closed sock1.
        sock2.enqueue_recv(canned_connack_bytes(return_code=0))
        client.connect()
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED
        assert client.last_error is None


class TestFromConfigGuard:
    def test_from_config_rejects_non_mapping(self):
        with raises(ValueError):
            MQTTClient.from_config(None, socket=FakeSocket())
