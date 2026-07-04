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
    canned_suback_bytes,
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

    def test_puback_flood_does_not_crash_or_evict(self):
        # Many inbound QoS-1 publishes in one chunk generate more PUBACKs
        # than the queue drains per tick; the headroom bound must hold
        # without raising (MP/CP) or evicting (CPython).
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks, max_tx_queue_size=4)
        chunk = b"".join(
            canned_publish_bytes("t", b"x", qos=1, packet_id=(index % 60) + 1)
            for index in range(120)
        )
        sock.enqueue_recv(chunk)
        drive(client, ticks, count=1)  # dispatches all, floods PUBACKs
        assert client.state == ProtocolState.CONNECTED


class TestWritabilityAndCallbacks:
    def test_io_interest_write_true_during_partial_send(self):
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)
        client._partial_send = (memoryview(b"partial"), 0)
        # Even with an empty queue, a partial send needs writability.
        while client._tx_queue:
            client._tx_queue.popleft()
        # CONNECTED always wants read; the partial send adds write.
        assert client.io_interest(ticks.ticks_ms()) == IO_READ | IO_WRITE

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


def _counting_factory(*socks):
    """Factory over *socks* that records the tick-time of each build."""
    iterator = iter(socks)
    build_times = []

    def factory():
        build_times.append(None)
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=next(iterator))

    return factory, build_times


def _failing_factory(ticks):
    """Factory whose connector always fails; records each build's tick-time."""
    build_times = []

    def factory():
        build_times.append(ticks.ticks_ms())
        return FakeSocketConnector(actions=["fail:wifi down"])

    return factory, build_times


class TestSelfHealBackoffAndPermanentFailure:
    def test_permanent_connack_rejection_stops_self_heal(self):
        # CONNACK code 5 (not authorized) can't be fixed by reconnecting
        # with the same credentials, so the client latches permanent
        # failure and never rebuilds the connector again.
        sock = FakeSocket()
        ticks = FakeTicks()
        factory, build_times = _counting_factory(sock)
        client = MQTTClient(transport_factory=factory, ticks=ticks, client_id="c")
        sock.enqueue_recv(canned_connack_bytes(return_code=5))
        client.connect()
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.FAILED
        assert client._permanent_failure is True
        # A permanent failure has no handle work left, so the runner is
        # told to stop ticking it.
        assert client.check(ticks.ticks_ms()) is False
        assert len(build_times) == 1  # initial connect only
        # Many ticks with time advancing: still no rebuild.
        for _ in range(20):
            ticks.advance(60000)
            drive(client, ticks, count=1)
        assert len(build_times) == 1
        assert client.state == ProtocolState.FAILED

    def test_transient_failure_backs_off_between_reconnects(self):
        # A connector that keeps failing must not rebuild every tick: the
        # first retry is immediate, later ones wait out an exponential
        # backoff.
        ticks = FakeTicks()
        factory, build_times = _failing_factory(ticks)
        client = MQTTClient(transport_factory=factory, ticks=ticks, client_id="c")
        client.connect()  # build #1 at connect()
        drive(client, ticks, count=1)  # connector fails -> FAILED
        assert client.state == ProtocolState.FAILED
        assert len(build_times) == 1
        # First self-heal fires immediately (no prior backoff armed).
        drive(client, ticks, count=1)
        assert len(build_times) == 2
        # No further rebuild until the 1 s base backoff elapses.
        for _ in range(5):
            drive(client, ticks, count=1)
        assert len(build_times) == 2
        # Advancing past the base interval frees exactly one more attempt.
        ticks.advance(1000)
        drive(client, ticks, count=1)
        assert len(build_times) == 3

    def test_suback_rejection_evicts_topic_from_subscriptions(self):
        # A 0x80 SUBACK faults the connection, but the rejected filter
        # must be dropped from _subscriptions first so the self-heal
        # reconnect's replay doesn't re-issue it and loop forever.
        sock1 = FakeSocket()
        sock2 = FakeSocket()
        ticks = FakeTicks()
        factory, _ = _counting_factory(sock1, sock2)
        client = MQTTClient(transport_factory=factory, ticks=ticks, client_id="c")
        sock1.enqueue_recv(canned_connack_bytes(return_code=0))
        client.connect()
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED
        client.subscribe("denied/topic", qos=1)
        drive(client, ticks, count=1)  # SUBSCRIBE hits the wire (packet_id 1)
        assert "denied/topic" in client._subscriptions
        sock1.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=0x80))
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED
        assert "denied/topic" not in client._subscriptions
