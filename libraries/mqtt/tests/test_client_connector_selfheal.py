"""mqtt client: connector-factory self-heal mechanics.

The reconnect-replay half (subscription replay, explicit-disconnect
gating) lives in ``test_client_selfheal_replay.py`` (suite-slimming
split).
"""

from chumicro_mqtt import (
    MQTTClient,
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_test_harness.assertions import raises
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


class TestConnectorFactorySelfHeal:
    """The wifi-drop survivability story.

    When ``MQTTClient`` is constructed with a ``transport_factory``, a
    tick in ``FAILED`` state builds a fresh connector via the factory
    and re-enters ``AWAITING_TRANSPORT``; subsequent ticks drive DNS /
    TCP / TLS without blocking the runner.  The caller's run loop sees
    mqtt come back without writing any recovery code.
    """

    def test_neither_socket_nor_factory_raises(self) -> None:
        with raises(ValueError, match="socket or a transport_factory"):
            MQTTClient(client_id="x")

    def test_factory_only_constructor_defers_socket_build_to_connect(self) -> None:
        """Factory is NOT called at construction.  Only when connect() runs.

        Construction is side-effect free: ``__init__`` must not open
        sockets, so network errors land in ``state == FAILED`` /
        ``last_error`` instead of propagating out of the constructor
        where the runner contract can't see them.
        """
        ticks = FakeTicks()
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        builds: list[FakeSocket] = []

        def factory():
            builds.append(sock)
            return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=sock)

        client = MQTTClient(
            transport_factory=factory,
            client_id="x",
            ticks=ticks,
        )
        # No connector built at construction.
        assert len(builds) == 0
        assert client.state == ProtocolState.DISCONNECTED

        client.connect()
        # Factory invoked exactly once during connect().
        assert len(builds) == 1
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        # Two ticks advance the connector (dns_ok then tcp_ok+CONNECT-drain);
        # third tick parses the CONNACK.
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED
        # Factory not called a second time.  The socket is healthy.
        assert len(builds) == 1

    def test_factory_failure_in_connect_marks_failed(self) -> None:
        """OSError from the factory at connect() time lands as FAILED + last_error."""
        ticks = FakeTicks()

        def factory():
            raise OSError(103, "ECONNABORTED")

        client = MQTTClient(
            transport_factory=factory,
            client_id="x",
            ticks=ticks,
        )
        # Construction succeeds with no I/O yet.
        assert client.state == ProtocolState.DISCONNECTED
        client.connect()
        # Factory error transitions to FAILED instead of propagating.
        assert client.state == ProtocolState.FAILED
        assert client.last_error is not None
        assert "factory failed" in str(client.last_error)

    def test_failed_state_with_factory_self_heals_and_reconnects(self) -> None:
        """Factory is called on FAILED + handle().  A new socket comes up."""
        ticks = FakeTicks()
        sock_one = FakeSocket()
        sock_two = FakeSocket()
        sock_one.enqueue_recv(canned_connack_bytes(return_code=0))
        sock_two.enqueue_recv(canned_connack_bytes(return_code=0))

        client = MQTTClient(
            transport_factory=_transport_factory(sock_one, sock_two),
            client_id="heal-test",
            ticks=ticks,
        )
        client.connect()
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED

        # Force FAILED to simulate a wifi-drop that killed the socket.
        client.state = ProtocolState.FAILED
        drive(client, ticks, count=3)

        # Self-heal ran: factory built a new connector, drove it to
        # ready, CONNACK arrived, back to CONNECTED on a different socket.
        assert client.state == ProtocolState.CONNECTED
        # The send on sock_two contains a CONNECT (post-self-heal handshake).
        assert b"\x10" in bytes(sock_two.sent)  # CONNECT first byte = 0x10

    def test_failed_state_without_factory_stays_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)  # no transport_factory

        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        client.state = ProtocolState.FAILED
        drive(client, ticks, count=5)
        # Without a factory there's no self-heal: client stays FAILED.
        assert client.state == ProtocolState.FAILED

    def test_factory_raise_keeps_client_failed(self) -> None:
        """Factory raises while wifi is down.  Client stays FAILED and retries after backoff."""
        ticks = FakeTicks()
        initial_sock = FakeSocket()
        initial_sock.enqueue_recv(canned_connack_bytes(return_code=0))
        recovery_sock = FakeSocket()
        recovery_sock.enqueue_recv(canned_connack_bytes(return_code=0))
        attempts: list[bool] = []

        def factory():
            if not attempts:
                attempts.append(True)  # initial connect() build
                return FakeSocketConnector(
                    actions=["dns_ok", "tcp_ok"], socket=initial_sock,
                )
            if len(attempts) < 4:
                attempts.append(False)
                raise OSError("wifi still down")
            attempts.append(True)
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=recovery_sock,
            )

        client = MQTTClient(
            transport_factory=factory,
            client_id="retry-test",
            ticks=ticks,
        )
        client.connect()
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED

        client.state = ProtocolState.FAILED
        # The first self-heal after a fresh failure fires immediately; the
        # factory raises, so the client stays FAILED.
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED
        assert "wifi still down" in str(client.last_error)

        # Later attempts are paced by exponential backoff.  Advance the
        # clock past each interval so the next retry fires; the factory
        # raises on its 2nd and 3rd calls, then hands back the recovery
        # connector on its 4th and self-heal succeeds.
        for _ in range(3):
            ticks.advance(60000)
            drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED
