"""mqtt client: Runner reactor contract (io_socket / io_interest / next_deadline)."""

import select

from chumicro_mqtt import (
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    drive,
    new_client,
)
from chumicro_runner import IO_READ, IO_WRITE, Runner
from chumicro_runner.testing import FakePoller
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


class TestRunnerReactorContract:
    """``io_socket`` / ``io_interest`` / ``next_deadline`` let
    ``Runner.wait`` register the broker socket and idle the loop until
    readiness or the next deadline fires."""

    def test_io_socket_none_when_disconnected(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        # state defaults to DISCONNECTED
        assert client.io_socket is None

    def test_io_socket_returns_socket_when_connected(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        # FakeSocket has no ``_sock``; the property returns it directly.
        # Production adapters expose ``_sock`` and the property unwraps.
        assert client.io_socket is sock

    def test_io_socket_none_when_failed(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.state = ProtocolState.FAILED

        assert client.io_socket is None

    def test_io_interest_read_only_while_live(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        assert client.io_interest(ticks.ticks_ms()) == 0  # DISCONNECTED

        client.connect()
        # CONNECTING wants read; the queued CONNECT also wants write.
        assert client.io_interest(ticks.ticks_ms()) == IO_READ | IO_WRITE
        drive(client, ticks, count=2)
        # CONNECTED, tx drained -> read only.
        assert client.io_interest(ticks.ticks_ms()) == IO_READ

    def test_io_interest_write_tracks_tx_queue(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        # DISCONNECTED + empty tx -> no interest at all.
        assert client.io_interest(ticks.ticks_ms()) == 0

        # connect() queues a CONNECT packet but does not drain yet.
        client.connect()
        assert client.io_interest(ticks.ticks_ms()) & IO_WRITE

        # Drain the CONNECT, receive CONNACK -> tx queue empty.
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        drive(client, ticks, count=2)
        assert not (client.io_interest(ticks.ticks_ms()) & IO_WRITE)

    def test_next_deadline_none_when_disconnected(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        assert client.next_deadline(ticks.ticks_ms()) is None

    def test_next_deadline_returns_pending_ack_when_connecting(self) -> None:
        """``connect()`` enqueues a PendingResponse for CONNACK with an
        ack-timeout deadline; that becomes the next deadline."""
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks, ack_timeout_seconds=2.0)
        start = ticks.ticks_ms()
        client.connect()
        deadline = client.next_deadline(ticks.ticks_ms())
        assert deadline is not None
        # ack_timeout is 2000 ms from connect().
        assert ticks.ticks_diff(deadline, start) == 2000

    def test_next_deadline_picks_keepalive_when_connected(self) -> None:
        """Once CONNECTED with no in-flight ACKs, next_deadline is the
        keepalive (PINGREQ-send) timer."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks, keep_alive_seconds=60, ack_timeout_seconds=5.0,
        )
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        deadline = client.next_deadline(ticks.ticks_ms())
        assert deadline is not None
        # Ping interval is half the keepalive (30000 ms from CONNECTED tick).
        # drive() advanced through 2 ticks; allow for that.
        assert ticks.ticks_diff(deadline, ticks.ticks_ms()) > 0

    def test_runner_wait_registers_socket_for_mqtt_lifecycle(self) -> None:
        """End-to-end: connect via Runner + FakePoller, observe POLLIN
        registration after the CONNECT drains, then unregister on
        disconnect."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        poller = FakePoller()
        runner = Runner(ticks=ticks, poller=poller)
        client = new_client(sock, ticks)
        runner.add(client)
        client.connect()

        # First wait observes write interest (CONNECT queued), so
        # the poll set should request POLLIN|POLLOUT initially.
        runner.wait(ticks.ticks_ms())
        first_marks = poller.register_calls + poller.modify_calls
        assert any(
            eventmask & select.POLLOUT
            for _sock, eventmask in first_marks
        )

        # Drive ticks to drain CONNECT and receive CONNACK.
        for _ in range(5):
            now_ms = runner.tick()
            runner.wait(now_ms)
            ticks.advance(1)
        assert client.state == ProtocolState.CONNECTED
        assert not (client.io_interest(ticks.ticks_ms()) & IO_WRITE)  # tx queue drained

        # CONNECTED + empty tx queue: only POLLIN remains.
        last_event = (
            poller.modify_calls[-1] if poller.modify_calls else poller.register_calls[-1]
        )
        _last_sock, last_mask = last_event
        assert last_mask == select.POLLIN

        # disconnect() closes the socket and transitions to DISCONNECTED;
        # the next wait sees io_socket=None and unregisters.
        client.disconnect()
        runner.wait(ticks.ticks_ms())
        assert sock in poller.unregister_calls
