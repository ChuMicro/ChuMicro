"""mqtt client: self-heal reconnect replay + explicit-disconnect gating.

Split from ``test_client_connector_selfheal.py`` so each file fits the
unix-lane heap budget (suite-slimming convention); the connector-factory
self-heal mechanics stay there.
"""

from chumicro_mqtt import (
    MQTTClient,
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_suback_bytes,
    canned_unsuback_bytes,
    drive,
)
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks


def _transport_factory(*socks: FakeSocket):
    """Hand back successive scripted ``FakeSocketConnector``s.

    Each invocation pops the next socket and wraps it in a connector
    that runs ``dns_ok`` then ``tcp_ok`` — the shortest happy-path
    script.  Tests that need to exercise pending / failure phases
    build the connector directly.
    """
    iterator = iter(socks)

    def factory():
        sock = next(iterator)
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=sock)

    return factory


class TestSelfHealReconnectReplay:
    def test_explicit_disconnect_disables_self_heal(self) -> None:
        """User-driven disconnect() must not auto-reconnect via the factory."""
        ticks = FakeTicks()
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        builds: list[None] = []

        def factory():
            builds.append(None)
            return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=sock)

        client = MQTTClient(
            transport_factory=factory,
            client_id="disconnect-test",
            ticks=ticks,
        )
        client.connect()
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED
        initial_build_count = len(builds)

        client.disconnect()
        assert client.state == ProtocolState.DISCONNECTED

        # Force FAILED.  Even with the factory present, the user-driven
        # disconnect should keep self-heal off.
        client.state = ProtocolState.FAILED
        drive(client, ticks, count=5)
        assert client.state == ProtocolState.FAILED
        assert len(builds) == initial_build_count  # factory not called again

    def test_subscription_replayed_on_self_heal_reconnect(self) -> None:
        # After subscribe(), force FAILED, let self-heal rebuild the
        # socket and re-issue CONNECT.  The new CONNACK should trigger
        # a SUBSCRIBE replay so the inbound stream survives reconnect.
        # Without this, the client comes back on the wire but the
        # broker (with clean_session=True, the default) has forgotten
        # the subscription and inbound goes silent.
        ticks = FakeTicks()
        sock_one = FakeSocket()
        sock_two = FakeSocket()
        sock_one.enqueue_recv(canned_connack_bytes(return_code=0))
        sock_two.enqueue_recv(canned_connack_bytes(return_code=0))

        client = MQTTClient(
            transport_factory=_transport_factory(sock_one, sock_two),
            client_id="resub-test",
            ticks=ticks,
        )
        client.connect()
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED

        client.subscribe("sensors/+", qos=1)
        drive(client, ticks, count=1)
        sock_one.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=1))
        drive(client, ticks, count=1)

        # Force FAILED to simulate broker death; self-heal rebuilds.
        client.state = ProtocolState.FAILED
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED

        # Post-CONNACK replay enqueued a SUBSCRIBE and the
        # post-read drain sent it.  0x82 = SUBSCRIBE control byte.
        assert b"\x82" in bytes(sock_two.sent)

    def test_unsubscribed_topic_not_replayed_on_reconnect(self) -> None:
        # Subscribe then unsubscribe, then force a self-heal cycle.
        # The unsubscribed topic must not be replayed — _subscriptions
        # is eagerly maintained, so unsubscribe() removes it before
        # the UNSUBACK round-trip completes.
        ticks = FakeTicks()
        sock_one = FakeSocket()
        sock_two = FakeSocket()
        sock_one.enqueue_recv(canned_connack_bytes(return_code=0))
        sock_two.enqueue_recv(canned_connack_bytes(return_code=0))

        client = MQTTClient(
            transport_factory=_transport_factory(sock_one, sock_two),
            client_id="unsub-test",
            ticks=ticks,
        )
        client.connect()
        drive(client, ticks, count=3)
        client.subscribe("sensors/+", qos=1)
        drive(client, ticks, count=1)
        sock_one.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=1))
        drive(client, ticks, count=1)
        client.unsubscribe("sensors/+")
        drive(client, ticks, count=1)
        sock_one.enqueue_recv(canned_unsuback_bytes(packet_id=2))
        drive(client, ticks, count=1)

        # Force self-heal.
        client.state = ProtocolState.FAILED
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED

        # No SUBSCRIBE on sock_two.
        assert b"\x82" not in bytes(sock_two.sent)
