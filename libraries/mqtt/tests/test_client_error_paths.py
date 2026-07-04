"""mqtt client: error paths, decoder edge cases, disconnected-state guards."""

from chumicro_mqtt import (
    MQTTError,
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


class TestErrorPaths:
    def test_handle_in_disconnected_returns_immediately(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        # No connect.  State is DISCONNECTED.
        # handle() should be a no-op (no recv attempt, no send).
        assert sock.sent == bytearray()
        client.handle(ticks.ticks_ms())
        assert sock.sent == bytearray()

    def test_check_returns_false_when_disconnected(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        assert client.check(ticks.ticks_ms()) is False

    def test_check_returns_true_when_failed(self) -> None:
        # The runner gates handle() on check(); _attempt_self_heal
        # only fires from inside handle()'s FAILED branch.  If check()
        # gates FAILED out, self-heal is unreachable and broker-outage
        # recovery never runs.
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state is ProtocolState.CONNECTED
        client.state = ProtocolState.FAILED
        assert client.check(ticks.ticks_ms()) is True

    def test_oserror_during_send_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        # Inject OSError on next send.
        original_send = sock.send

        def _broken_send(_data: bytes) -> int:
            raise OSError(2, "broken pipe")

        sock.send = _broken_send  # type: ignore[assignment]
        client.publish("x", b"y", qos=0)
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED
        sock.send = original_send  # type: ignore[assignment]

    def test_pingresp_timeout_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks, keep_alive_seconds=30)
        client.connect()
        drive(client, ticks, count=2)
        # Skip past keepalive.  PINGREQ goes out, no PINGRESP arrives.
        ticks.advance(15_500)
        drive(client, ticks, count=1)  # Sends PINGREQ, registers pending.
        ticks.advance(10_000)  # Past ack_timeout (5 s).
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED

    def test_send_timeout_marks_failed(self) -> None:
        """When the socket has been non-writable with a packet queued
        for longer than ``send_timeout_seconds``, the client transitions
        to FAILED so self-heal can rebuild the socket.  Without this
        timeout a NAT-style silent-drop on the outbound path would let
        the tx queue grow until ``MQTTBackpressureError`` -- the
        publisher sees the error, the client never noticed."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks, send_timeout_seconds=2.0)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        # Stuck socket: every send returns EAGAIN for the foreseeable future.
        sock.enqueue_eagain_for_send(1_000)
        client.publish("topic", b"hello", qos=0)
        # First drain attempts the send (EAGAIN), arms the deadline.
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.CONNECTED
        # Skip past the send timeout.
        ticks.advance(2_500)
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED
        assert "send timeout" in str(client.last_error)


class TestIoAndRetryErrorPaths:
    def test_send_timeout_clears_when_drain_makes_progress(self) -> None:
        """A steady drip of sends shouldn't trip the send timeout.  The
        deadline re-arms every successful drain."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks, send_timeout_seconds=2.0)
        client.connect()
        drive(client, ticks, count=2)
        # Publish then drive past the timeout window with successful sends
        # in between; deadline should never trip because every drain
        # re-arms.
        for _ in range(5):
            client.publish("topic", b"x", qos=0)
            drive(client, ticks, count=2)  # send + callback drain
            ticks.advance(1_500)  # under the 2s timeout
        assert client.state == ProtocolState.CONNECTED

    def test_io_error_marks_failed(self) -> None:
        """The runner's POLLERR / POLLHUP dispatch via io_error transitions
        the client to FAILED with a meaningful last_error so self-heal
        fires on the next tick."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        # Simulate Runner.wait dispatching POLLERR.
        client.io_error(ticks.ticks_ms(), 0x08)  # POLLERR
        assert client.state == ProtocolState.FAILED
        assert "0x8" in str(client.last_error)

    def test_io_error_noop_when_already_failed(self) -> None:
        """A second io_error against an already-FAILED client is a no-op."""
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.state = ProtocolState.FAILED
        first_error = MQTTError("first")
        client.last_error = first_error

        client.io_error(ticks.ticks_ms(), 0x08)
        # last_error not overwritten by the no-op call.
        assert client.last_error is first_error

    def test_peer_close_marks_failed(self) -> None:
        """A clean FIN from the broker (``recv_into() == 0``) transitions
        the client to FAILED so the runner can self-heal.  The bug fixed
        here was a silent ``break`` that left ``state == CONNECTED`` even
        after the peer hung up; deadline detection couldn't recover the
        connection on its own because nothing armed a deadline."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        # Broker hangs up cleanly.
        sock.simulate_peer_close()
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED

    def test_qos1_exceeds_retry_limit_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks, publish_retry_max=1)
        client.connect()
        drive(client, ticks, count=2)
        client.publish("x", b"y", qos=1)
        drive(client, ticks, count=1)
        # No PUBACK ever arrives.  Two ack-timeouts: first triggers
        # one retry, second exceeds publish_retry_max, marking FAILED.
        ticks.advance(10_000)
        drive(client, ticks, count=1)
        ticks.advance(10_000)
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED
