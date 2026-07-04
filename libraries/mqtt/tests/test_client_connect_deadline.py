"""mqtt client: the connect-attempt deadline while awaiting transport.

Split from ``test_client_multitick_connect.py`` so each file fits the
unix-lane heap budget (suite-slimming convention).
"""

from chumicro_mqtt import (
    MQTTClient,
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
)
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks


class TestConnectAttemptDeadline:
    """The client owns the transport-attempt deadline.

    Connectors report ``next_deadline() is None`` by design, so without
    a consumer-side bound a black-holed TCP connect (NAT silent drop)
    would park AWAITING_TRANSPORT forever.  The window inherits
    ``ack_timeout_seconds`` — no separate knob."""

    def _stalled_client(self, ticks):
        """Client whose connector reaches awaiting_tcp then never progresses."""
        built = []

        def factory():
            connector = FakeSocketConnector(
                actions=["dns_ok"], socket=FakeSocket(),
            )
            built.append(connector)
            return connector

        client = MQTTClient(
            transport_factory=factory,
            client_id="stall-test",
            ticks=ticks,
        )
        return client, built

    def test_stalled_tcp_connect_faults_at_attempt_deadline(self) -> None:
        ticks = FakeTicks()
        client, built = self._stalled_client(ticks)
        client.connect()
        # dns_ok consumes the script; the connector then idles in
        # awaiting_tcp with no further transitions (SYN black-holed).
        client.handle(ticks.ticks_ms())
        ticks.advance(2000)
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        # Cross the ack_timeout_seconds window: the attempt faults.
        ticks.advance(3000)
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.FAILED
        assert "timed out" in str(client.last_error)
        assert "awaiting_tcp" in str(client.last_error)
        # The connector was cancelled and disposed, not leaked mid-flight.
        assert client._connector is None  # noqa: SLF001
        assert built[0].state == "failed"

    def test_timeout_fault_reschedules_through_self_heal(self) -> None:
        ticks = FakeTicks()
        client, built = self._stalled_client(ticks)
        client.connect()
        client.handle(ticks.ticks_ms())
        ticks.advance(5000)
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.FAILED
        # Next tick self-heals: a fresh connector, a fresh attempt
        # deadline, back in AWAITING_TRANSPORT.
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        assert len(built) == 2
        assert client._transport_deadline_ticks is not None  # noqa: SLF001

    def test_deadline_cleared_when_connect_completes_in_time(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=sock)

        client = MQTTClient(
            transport_factory=factory,
            client_id="in-time",
            ticks=ticks,
        )
        client.connect()
        client.handle(ticks.ticks_ms())
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.CONNECTED
        # The attempt window dies with the attempt: no stale deadline
        # left to fault a healthy connection later.
        assert client._transport_deadline_ticks is None  # noqa: SLF001

    def test_disconnect_mid_attempt_is_idempotent(self) -> None:
        """disconnect() during an in-flight attempt cancels the
        connector, fires on_disconnect exactly once, and a second call
        is a no-op."""
        ticks = FakeTicks()
        client, built = self._stalled_client(ticks)
        fired = []
        client.on_disconnect = lambda: fired.append(1)
        client.connect()
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.AWAITING_TRANSPORT

        client.disconnect()
        assert client.state == ProtocolState.DISCONNECTED
        assert client._connector is None  # noqa: SLF001
        assert client._transport_deadline_ticks is None  # noqa: SLF001
        assert built[0].state == "failed"  # cancel() ran

        client.disconnect()
        assert client.state == ProtocolState.DISCONNECTED
        assert fired == [1]  # exactly one on_disconnect across both calls
