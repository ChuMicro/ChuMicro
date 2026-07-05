"""mqtt client: connect() as an intent, not a state-transition guard.

From DISCONNECTED it dials as before; from FAILED it triggers the SAME
self-heal reconnect *immediately* (cancel armed backoff, reset the
schedule, dial this tick-cycle) rather than raising; from
AWAITING_TRANSPORT / CONNECTING / CONNECTED it is an idempotent no-op
(the "be connected" intent is already satisfied — and no second
connector races the in-flight one).  The caller-driven hold() half lives
in ``test_client_hold_reconnect``; publish-fate-across-outage in
``test_client_wifi_outage_publish_fate``; backoff mechanics in
``test_client_selfheal_backoff``.
"""

from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_mqtt.testing import canned_connack_bytes, drive, new_client
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks


def _factory(*socks):
    """Factory over *socks* whose connectors succeed (dns_ok, tcp_ok)."""
    iterator = iter(socks)

    def factory():
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=next(iterator))

    return factory


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
    client = MQTTClient(transport_factory=factory, client_id="intent", ticks=ticks)
    client.connect()
    drive(client, ticks, count=3)
    assert client.state == ProtocolState.CONNECTED
    return client, builds


class TestConnectIsIntent:
    def test_connect_from_failed_dials_immediately_short_circuiting_backoff(self):
        # The 12 s-wasted bench case: a FAILED client with a grown backoff
        # would wait out residual backoff before the timer re-dials.
        # connect() resets the schedule and dials THIS tick-cycle instead.
        ticks = FakeTicks()
        factory, builds = _failing_factory(ticks)
        client = MQTTClient(transport_factory=factory, ticks=ticks, client_id="c")
        client.connect()                 # build #1 -> AWAITING_TRANSPORT
        drive(client, ticks, count=1)    # connector fails -> FAILED
        assert client.state == ProtocolState.FAILED
        assert len(builds) == 1
        # First self-heal fires immediately, then backoff paces the rest.
        drive(client, ticks, count=1)     # build #2 (immediate)
        ticks.advance(1000)
        drive(client, ticks, count=1)     # build #3
        ticks.advance(2000)
        drive(client, ticks, count=1)     # build #4
        assert len(builds) == 4
        assert client._self_heal_attempts > 0                # noqa: SLF001
        assert client._self_heal_retry_at_ticks is not None  # noqa: SLF001
        # Parked on the grown backoff: a plain tick will not dial.
        drive(client, ticks, count=1)
        assert len(builds) == 4
        # The app knows the link is back: connect() forces an immediate
        # dial with no clock advance.
        client.connect()
        assert client._self_heal_attempts == 0                 # noqa: SLF001
        assert client._self_heal_retry_at_ticks is None        # noqa: SLF001
        assert client.next_deadline(ticks.ticks_ms()) == ticks.ticks_ms()
        drive(client, ticks, count=1)
        assert len(builds) == 5          # dialed immediately

    def test_failure_after_connect_repaces_backoff_from_base(self):
        # connect() resets the schedule, so the NEXT failure re-paces from
        # the 1 s base rather than the grown interval.
        ticks = FakeTicks()
        factory, builds = _failing_factory(ticks)
        client = MQTTClient(transport_factory=factory, ticks=ticks, client_id="c")
        client.connect()
        drive(client, ticks, count=1)     # fail -> FAILED
        drive(client, ticks, count=1)     # build #2, attempts=1
        ticks.advance(1000)
        drive(client, ticks, count=1)     # build #3, attempts=2
        ticks.advance(2000)
        drive(client, ticks, count=1)     # build #4, attempts=3
        assert client._self_heal_attempts == 3               # noqa: SLF001
        client.connect()
        assert client._self_heal_attempts == 0               # noqa: SLF001
        now = ticks.ticks_ms()
        drive(client, ticks, count=1)     # first post-connect attempt
        # Re-paced from the base: the newly armed wait is one 1 s interval.
        assert client._self_heal_attempts == 1               # noqa: SLF001
        assert ticks.ticks_diff(client._self_heal_retry_at_ticks, now) == 1000  # noqa: SLF001

    def test_connect_when_connected_is_noop_and_clears_hold(self):
        ticks = FakeTicks()
        client, _ = _connected(ticks, FakeSocket(), FakeSocket())
        sent_before = bytes(client._socket.sent)  # noqa: SLF001
        # A preemptive hold latched while CONNECTED is lifted by connect(),
        # and no second CONNECT packet is queued.
        client.hold()
        assert client._reconnect_held is True     # noqa: SLF001
        client.connect()
        assert client.state == ProtocolState.CONNECTED
        assert client._reconnect_held is False    # noqa: SLF001
        assert bytes(client._socket.sent) == sent_before  # noqa: SLF001

    def test_connect_when_awaiting_transport_is_noop_no_second_connector(self):
        # The double-actor guard the old raise provided is preserved here:
        # a second connect() while a dial is in flight builds no second
        # connector.
        ticks = FakeTicks()
        factory, builds = _counting_factory(FakeSocket(), FakeSocket())
        client = MQTTClient(transport_factory=factory, ticks=ticks, client_id="c")
        client.connect()
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        assert len(builds) == 1
        connector_before = client._connector  # noqa: SLF001
        client.connect()
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        assert len(builds) == 1
        assert client._connector is connector_before  # noqa: SLF001

    def test_connect_when_connecting_is_noop(self):
        ticks = FakeTicks()
        sock = FakeSocket()
        client = new_client(sock, ticks)
        client.connect()  # pre-built socket -> CONNECTING immediately
        assert client.state == ProtocolState.CONNECTING
        sent_before = bytes(sock.sent)
        client.connect()
        assert client.state == ProtocolState.CONNECTING
        assert bytes(sock.sent) == sent_before

    def test_queue_fate_identical_for_timer_and_connect_reconnect(self):
        # connect() from FAILED is "self-heal now," not a third path: the
        # raced-in-flight-dropped / buffered-flushed fate is identical
        # whether the timer or connect() drives the reconnect.
        def run_outage(reconnect_via_connect):
            ticks = FakeTicks()
            sock_one, sock_two = FakeSocket(), FakeSocket()
            sock_one.enqueue_recv(canned_connack_bytes(return_code=0))
            client = MQTTClient(
                transport_factory=_factory(sock_one, sock_two),
                client_id="equiv",
                clean_session=True,
                ticks=ticks,
            )
            client.connect()
            drive(client, ticks, count=3)
            assert client.state == ProtocolState.CONNECTED
            client.publish("raced", b"lost", qos=1)   # in-flight on doomed sock
            drive(client, ticks, count=1)
            client.state = ProtocolState.FAILED
            client.publish("buffered", b"kept", qos=1)  # buffered post-drop
            sock_two.enqueue_recv(canned_connack_bytes(return_code=0))
            if reconnect_via_connect:
                client.connect()
            drive(client, ticks, count=4)
            assert client.state == ProtocolState.CONNECTED
            recovered = bytes(sock_two.sent)
            return {
                # Raced qos-1 entry reset by the clean_session self-heal;
                # the buffered qos-1 flush re-opens exactly one in-flight
                # entry (awaiting its PUBACK) on the new socket.
                "in_flight_count": len(client._in_flight),  # noqa: SLF001
                "queue_len": len(client._pre_connect_queue),  # noqa: SLF001
                "raced_on_wire": b"raced" in recovered,
                "buffered_on_wire": b"buffered" in recovered,
            }

        timer = run_outage(reconnect_via_connect=False)
        user = run_outage(reconnect_via_connect=True)
        assert timer == user
        assert user == {
            "in_flight_count": 1,
            "queue_len": 0,
            "raced_on_wire": False,
            "buffered_on_wire": True,
        }
