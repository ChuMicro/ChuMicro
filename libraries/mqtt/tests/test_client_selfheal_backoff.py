"""mqtt client: self-heal backoff pacing + permanent-failure latch.

Split from ``test_client_audit_fixes.py`` so each file fits the
unix-lane heap budget (suite-slimming convention).
"""

from chumicro_mqtt import (
    MQTTClient,
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_suback_bytes,
    drive,
)
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks


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

    def test_next_deadline_wakes_runner_for_self_heal(self):
        # A self-heal-eligible FAILED client must surface a deadline so
        # Runner.wait parks-with-a-bound instead of sleeping on some
        # other service's socket: now_ms before any backoff is armed
        # (fresh failure, retry is immediate), the backoff deadline after.
        ticks = FakeTicks()
        factory, build_times = _failing_factory(ticks)
        client = MQTTClient(transport_factory=factory, ticks=ticks, client_id="c")
        client.connect()
        drive(client, ticks, count=1)  # connector fails -> FAILED
        assert client.state == ProtocolState.FAILED
        # No backoff armed yet: wake immediately.
        assert client.next_deadline(ticks.ticks_ms()) == ticks.ticks_ms()
        # The immediate retry arms the backoff; the deadline now names
        # the next allowed attempt.
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED
        retry_at = client._self_heal_retry_at_ticks  # noqa: SLF001
        assert retry_at is not None
        assert client.next_deadline(ticks.ticks_ms()) == retry_at
        assert len(build_times) == 2

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
