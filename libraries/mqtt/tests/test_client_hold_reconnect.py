"""mqtt client: caller-driven hold() over self-heal reconnection.

The symmetric mate of intent-based ``connect()`` (see
``test_client_connect_intent``): an app that KNOWS the link is down
suspends the self-heal timer so it stops dialing into a dead radio.
While held a FAILED client does not dial, keeps ``last_error``, and
parks ``next_deadline``; publishes still buffer per ``when_disconnected``;
``connect()`` is the release.
"""

from chumicro_mqtt import MQTTClient, MQTTError, ProtocolState
from chumicro_mqtt.testing import canned_connack_bytes, drive
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks


def _counting_factory(*socks):
    """Succeeding factory that records each connector build."""
    iterator = iter(socks)
    builds = []

    def factory():
        builds.append(None)
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=next(iterator))

    return factory, builds


def _failing_factory(ticks):
    """Factory whose connector always fails; records each build's tick-time."""
    builds = []

    def factory():
        builds.append(ticks.ticks_ms())
        return FakeSocketConnector(actions=["fail:wifi down"])

    return factory, builds


def _connected(ticks, *socks):
    """Factory-backed client driven to CONNECTED on the first socket."""
    factory, builds = _counting_factory(*socks)
    socks[0].enqueue_recv(canned_connack_bytes(return_code=0))
    client = MQTTClient(transport_factory=factory, client_id="hold", ticks=ticks)
    client.connect()
    drive(client, ticks, count=3)
    assert client.state == ProtocolState.CONNECTED
    return client, builds


class TestHoldSuspendsReconnect:
    def test_hold_suppresses_timer_self_heal_and_preserves_last_error(self):
        ticks = FakeTicks()
        client, builds = _connected(ticks, FakeSocket(), FakeSocket())
        # The app learns the radio dropped and holds reconnection down.
        client.hold()
        client.state = ProtocolState.FAILED
        sentinel = MQTTError("link down")
        client.last_error = sentinel
        # Time passes, many ticks: a held client never rebuilds transport.
        for _ in range(10):
            ticks.advance(60000)
            drive(client, ticks, count=1)
        assert len(builds) == 1                    # initial connect only
        assert client.state == ProtocolState.FAILED
        assert client.last_error is sentinel        # preserved; no dial touched it

    def test_publish_while_held_buffers_into_pre_connect_queue(self):
        ticks = FakeTicks()
        client, _ = _connected(ticks, FakeSocket(), FakeSocket())
        client.hold()
        client.state = ProtocolState.FAILED
        client.publish("held/topic", b"payload", qos=1)
        assert len(client._pre_connect_queue) == 1  # noqa: SLF001
        # Still held: driving neither dials nor drains.
        drive(client, ticks, count=3)
        assert len(client._pre_connect_queue) == 1  # noqa: SLF001
        assert client.state == ProtocolState.FAILED

    def test_next_deadline_parks_and_check_gates_out_while_held(self):
        ticks = FakeTicks()
        factory, builds = _failing_factory(ticks)
        client = MQTTClient(transport_factory=factory, ticks=ticks, client_id="c")
        client.connect()
        drive(client, ticks, count=1)  # fail -> FAILED
        assert client.state == ProtocolState.FAILED
        # Self-heal-active: wakes immediately and wants a handle().
        assert client.next_deadline(ticks.ticks_ms()) == ticks.ticks_ms()
        assert client.check(ticks.ticks_ms()) is True
        # Held: the runner parks (no deadline) and skips the handle.
        client.hold()
        assert client.next_deadline(ticks.ticks_ms()) is None
        assert client.check(ticks.ticks_ms()) is False
        # Released: the immediate wake is re-armed.
        client.connect()
        assert client.next_deadline(ticks.ticks_ms()) == ticks.ticks_ms()
        assert client.check(ticks.ticks_ms()) is True

    def test_connect_releases_hold_dials_now_and_flushes_queue(self):
        ticks = FakeTicks()
        sock_one, sock_two = FakeSocket(), FakeSocket()
        client, builds = _connected(ticks, sock_one, sock_two)
        client.hold()
        client.state = ProtocolState.FAILED
        client.publish("held", b"kept", qos=1)
        # Held across many ticks: no dial.
        for _ in range(5):
            ticks.advance(10000)
            drive(client, ticks, count=1)
        assert len(builds) == 1
        assert client.state == ProtocolState.FAILED
        # Link is back: connect() releases the hold and dials now.
        sock_two.enqueue_recv(canned_connack_bytes(return_code=0))
        client.connect()
        assert client._reconnect_held is False  # noqa: SLF001
        drive(client, ticks, count=4)
        assert client.state == ProtocolState.CONNECTED
        assert len(builds) == 2                 # dialed on release
        assert b"held" in bytes(sock_two.sent)  # queued publish flushed
        assert len(client._pre_connect_queue) == 0  # noqa: SLF001

    def test_hold_while_connected_is_latched_and_activates_on_failure(self):
        ticks = FakeTicks()
        client, builds = _connected(ticks, FakeSocket(), FakeSocket())
        # Preemptive hold while still CONNECTED (wifi reported down, mqtt
        # hasn't detected the drop yet): latched but dormant.
        client.hold()
        assert client._reconnect_held is True     # noqa: SLF001
        assert client.state == ProtocolState.CONNECTED
        assert client.check(ticks.ticks_ms()) is True  # CONNECTED keeps ticking
        # The failure lands; now the latch takes effect.
        client.state = ProtocolState.FAILED
        assert client.check(ticks.ticks_ms()) is False
        assert client.next_deadline(ticks.ticks_ms()) is None
        for _ in range(5):
            ticks.advance(10000)
            drive(client, ticks, count=1)
        assert len(builds) == 1                   # never dialed while held
