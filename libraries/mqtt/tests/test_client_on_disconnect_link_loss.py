"""mqtt client: on_disconnect fires when an established session drops."""

from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def _connected_client(sock, ticks, **overrides):
    sock.enqueue_recv(canned_connack_bytes(return_code=0))
    client = new_client(sock, ticks, **overrides)
    client.connect()
    drive(client, ticks, count=2)
    assert client.state is ProtocolState.CONNECTED
    return client


class TestLinkLossFiresOnDisconnect:
    def test_io_error_from_connected_fires_once(self) -> None:
        """POLLERR on an established session fires on_disconnect exactly
        once, after the client has settled into FAILED."""
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)
        seen = []
        client.on_disconnect = lambda: seen.append(client.state)

        client.io_error(ticks.ticks_ms(), 0x08)
        assert seen == [ProtocolState.FAILED]

    def test_handle_fault_from_connected_fires_once(self) -> None:
        """An OSError raised mid-tick on an established session fires
        on_disconnect, and last_error is already set when it does."""
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)
        errors_seen = []
        client.on_disconnect = lambda: errors_seen.append(client.last_error)

        def _broken_send(_data: bytes) -> int:
            raise OSError(32, "broken pipe")

        sock.send = _broken_send  # type: ignore[assignment]
        client.publish("topic", b"payload", qos=0)
        drive(client, ticks, count=1)
        assert client.state is ProtocolState.FAILED
        assert len(errors_seen) == 1
        assert "socket error" in str(errors_seen[0])

    def test_ack_timeout_from_connected_fires_once(self) -> None:
        """A PINGRESP that never arrives drops the established session
        and fires on_disconnect once."""
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks, keep_alive_seconds=30)
        fired = []
        client.on_disconnect = lambda: fired.append(1)

        ticks.advance(15_500)
        drive(client, ticks, count=1)  # PINGREQ goes out, response pending.
        ticks.advance(10_000)  # Past the 5 s ack timeout.
        drive(client, ticks, count=1)
        assert client.state is ProtocolState.FAILED
        assert fired == [1]


class TestConnectAttemptsStaySilent:
    def test_connack_rejection_does_not_fire(self) -> None:
        """A broker rejection lands before the session is established, so
        on_disconnect stays silent: the client never was connected."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=5))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        fired = []
        client.on_disconnect = lambda: fired.append(1)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state is ProtocolState.FAILED
        assert fired == []

    def test_factory_failure_does_not_fire(self) -> None:
        """A transport factory that raises fails the connect attempt from
        DISCONNECTED; no session existed, so on_disconnect stays silent."""

        def _broken_factory():
            raise OSError("no radio")

        ticks = FakeTicks()
        client = MQTTClient(
            transport_factory=_broken_factory,
            client_id="test-client",
            ticks=ticks,
        )
        fired = []
        client.on_disconnect = lambda: fired.append(1)
        client.connect()
        assert client.state is ProtocolState.FAILED
        assert fired == []

    def test_self_heal_retry_failures_stay_silent_after_one_fire(self) -> None:
        """Link loss fires on_disconnect once; the self-heal attempts that
        follow fail from AWAITING_TRANSPORT and add nothing."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        attempts = []

        def _factory():
            attempts.append(1)
            raise OSError("still down")

        client = MQTTClient(
            socket=sock,
            transport_factory=_factory,
            client_id="test-client",
            keep_alive_seconds=60,
            ticks=ticks,
        )
        fired = []
        client.on_disconnect = lambda: fired.append(1)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state is ProtocolState.CONNECTED

        client.io_error(ticks.ticks_ms(), 0x10)  # POLLHUP: link loss.
        assert fired == [1]
        # Drive through several backoff windows; each factory failure
        # re-enters FAILED from a non-established state.
        for _ in range(4):
            ticks.advance(70_000)
            drive(client, ticks, count=1)
        assert len(attempts) >= 2
        assert fired == [1]


class TestCallbackReentrancy:
    def test_reentrant_disconnect_settles_disconnected(self) -> None:
        """on_disconnect calling disconnect() ends DISCONNECTED: the
        link-loss fire and the explicit-disconnect fire each land once."""
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)
        calls = []

        def _bail():
            calls.append(client.state)
            if len(calls) == 1:
                client.disconnect()

        client.on_disconnect = _bail
        client.io_error(ticks.ticks_ms(), 0x08)
        assert calls == [ProtocolState.FAILED, ProtocolState.DISCONNECTED]
        assert client.state is ProtocolState.DISCONNECTED

    def test_reentrant_connect_rearms_self_heal(self) -> None:
        """on_disconnect calling connect() clears the backoff counters so
        the next tick rebuilds transport through the factory."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        replacement = FakeSocket()
        replacement.enqueue_recv(canned_connack_bytes(return_code=0))

        class _InstantConnector:
            state = "ready"
            socket = replacement

            def tick(self, _now_ms):
                return None

            def cancel(self):
                return None

        client = MQTTClient(
            socket=sock,
            transport_factory=_InstantConnector,
            client_id="test-client",
            keep_alive_seconds=60,
            ticks=ticks,
        )
        client.connect()
        drive(client, ticks, count=2)
        assert client.state is ProtocolState.CONNECTED

        client.on_disconnect = lambda: client.connect()
        client.io_error(ticks.ticks_ms(), 0x08)
        assert client.state is ProtocolState.FAILED
        drive(client, ticks, count=3)
        assert client.state is ProtocolState.CONNECTED
