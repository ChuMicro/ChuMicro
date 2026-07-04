"""mqtt client: socket blocking mode, connect, disconnect, set-will."""


from chumicro_mqtt import (
    MQTTClient,
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
)
from chumicro_runner import IO_WRITE
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks


class TestMultiTickConnect:
    """Connector-driven non-blocking connect.

    ``connect()`` returns immediately after arming the connector;
    DNS / TCP / TLS happen across subsequent ``handle()`` ticks so the
    runner is never blocked waiting on the network."""

    def test_connect_returns_immediately_in_awaiting_transport(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=sock,
            )

        client = MQTTClient(
            transport_factory=factory,
            client_id="multitick",
            ticks=ticks,
        )
        client.connect()
        # No network I/O on the caller's thread: state is AWAITING_TRANSPORT,
        # the CONNECT packet has not yet been queued, sock is untouched.
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        assert bytes(sock.sent) == b""

    def test_ticks_drive_through_dns_tcp_and_connect(self) -> None:
        """Tick 1 advances dns_ok; tick 2 advances tcp_ok, promotes the
        socket, drains CONNECT and (because CONNACK is pre-queued in
        the FakeSocket) reads it the same tick.  On a real wire the
        CONNACK arrives ticks later and the state lingers in CONNECTING
        between."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=sock,
            )

        client = MQTTClient(
            transport_factory=factory,
            client_id="multitick",
            ticks=ticks,
        )
        client.connect()

        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        assert bytes(sock.sent) == b""

        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.CONNECTED
        assert sock.sent[0] == 0x10  # CONNECT control byte landed on the wire

    def test_connector_failure_during_dns_lands_failed(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["fail:dns lookup failed"], socket=sock,
            )

        client = MQTTClient(
            transport_factory=factory,
            client_id="multitick",
            ticks=ticks,
        )
        client.connect()
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.FAILED
        assert "connector failed" in str(client.last_error)
        assert "dns lookup failed" in str(client.last_error)

    def test_connector_failure_during_tcp_lands_failed(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "fail:connection refused"], socket=sock,
            )

        client = MQTTClient(
            transport_factory=factory,
            client_id="multitick",
            ticks=ticks,
        )
        client.connect()
        client.handle(ticks.ticks_ms())  # dns_ok
        client.handle(ticks.ticks_ms())  # fail
        assert client.state == ProtocolState.FAILED
        assert "connection refused" in str(client.last_error)


class TestMultiTickConnectYield:
    """Yielding, cancellation, and deadline behavior while awaiting transport."""

    def test_tls_handshake_yields_between_rounds(self) -> None:
        """TLS connector scripts a ``tls_pending`` round-trip; the client
        stays in AWAITING_TRANSPORT until ``tls_ok`` lands.  Demonstrates
        the runner doesn't see a multi-tick handshake as a single
        blocking call."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok", "tls_pending", "tls_ok"],
                socket=sock,
                tls=True,
            )

        client = MQTTClient(
            transport_factory=factory,
            client_id="tls-multitick",
            ticks=ticks,
        )
        client.connect()
        # dns_ok
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        # tcp_ok → awaiting_tls (does not enter ready because tls=True)
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        # tls_pending → still awaiting_tls
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        # tls_ok → ready → promote → CONNECT drained → CONNACK read → CONNECTED
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.CONNECTED

    def test_disconnect_during_awaiting_transport_cancels_connector(self) -> None:
        """A user-driven ``disconnect()`` mid-handshake cancels the
        in-flight connector and lands in DISCONNECTED — no DISCONNECT
        packet, the MQTT layer never came up."""
        sock = FakeSocket()
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_pending", "tcp_ok"], socket=sock,
            )

        client = MQTTClient(
            transport_factory=factory,
            client_id="cancel-test",
            ticks=ticks,
        )
        client.connect()
        client.handle(ticks.ticks_ms())  # dns_ok
        assert client.state == ProtocolState.AWAITING_TRANSPORT

        client.disconnect()
        assert client.state == ProtocolState.DISCONNECTED
        # Connector dropped, no half-open socket retained.
        assert client._connector is None  # noqa: SLF001

    def test_connector_io_surface_forwarded_in_awaiting_transport(self) -> None:
        """``Runner.wait`` reads io_socket / io_interest / next_deadline
        off the client — during AWAITING_TRANSPORT they forward to the
        connector so the runner parks on the right pollable."""
        sock = FakeSocket()
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_pending", "tcp_ok"], socket=sock,
            )

        client = MQTTClient(
            transport_factory=factory,
            client_id="io-surface",
            ticks=ticks,
        )
        client.connect()
        # connector starts in awaiting_dns; one tick advances to awaiting_tcp
        # where io_interest is write-only (TCP connect phase needs POLLOUT).
        client.handle(ticks.ticks_ms())
        assert client.io_socket is sock
        assert client.io_interest(ticks.ticks_ms()) == IO_WRITE
        # The connector reports no deadline of its own; the client's
        # transport-attempt deadline (ack_timeout_seconds after
        # connect(), armed at tick 0 here) flows through so the runner
        # parks with a bound instead of forever.
        assert client.next_deadline(0) == 5000

    def test_next_deadline_clamps_to_now_while_awaiting_dns(self) -> None:
        """Before the connector builds a socket (awaiting_dns, io_socket
        None), next_deadline returns now_ms so Runner.wait ticks the
        connector forward instead of sleeping; once dns_ok produces a
        pollable, the transport-attempt deadline flows through (the
        connector itself reports none)."""
        sock = FakeSocket()
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=sock,
            )

        client = MQTTClient(
            transport_factory=factory,
            client_id="clamp-test",
            ticks=ticks,
        )
        client.connect()
        # Fresh connector is in awaiting_dns: no socket yet, nothing for
        # Runner.wait to park on, so the deadline collapses to now_ms.
        assert client.io_socket is None
        assert client.next_deadline(777) == 777
        # One tick drives dns_ok; the connector now exposes its socket
        # and the clamp lifts to the transport-attempt deadline.
        client.handle(ticks.ticks_ms())
        assert client.io_socket is sock
        assert client.next_deadline(777) == 5000
