"""requests client: runner reactor contract — io_socket / io_interest /
next_deadline let Runner.wait register and sleep.
"""

import select

from chumicro_requests import HttpClient
from chumicro_requests.testing import (
    canned_response,
    drive_until_done,
    make_client,
    make_factory,
)
from chumicro_runner import IO_READ, IO_WRITE, Runner
from chumicro_runner.testing import FakePoller
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


class TestRunnerReactorContract:
    """``io_socket`` / ``io_interest`` / ``next_deadline`` let
    ``Runner.wait`` register the in-flight socket and sleep until its
    readiness or the request timeout."""

    def test_io_socket_none_when_idle(self):
        client, _ticks, _ = make_client()
        assert client.io_socket is None

    def test_io_socket_returns_socket_in_flight(self):
        socket = FakeSocket()
        client, ticks, _ = make_client(socket_or_factory=socket)
        client.get("http://example.test/")
        # At ``awaiting_dns`` the connector has not built its socket, so
        # the pollable is ``None``; one ``handle`` drives ``dns_ok`` and
        # the connector's socket goes live.
        assert client.io_socket is None
        client.handle(ticks.ticks_ms())
        # FakeSocket has no ``_sock`` wrapping, so the property returns
        # the socket itself.  Production adapters expose ``_sock`` and
        # the property unwraps it for the poller.
        assert client.io_socket is socket

    def test_io_interest_write_only_during_send(self):
        socket = FakeSocket()
        # Stall the send so the request stays in SENDING.
        socket.enqueue_eagain_for_send(99)
        client, ticks, _ = make_client(socket_or_factory=socket)
        assert client.io_interest(ticks.ticks_ms()) == 0

        client.get("http://example.test/")
        client.handle(ticks.ticks_ms())  # drive into SENDING

        assert client.io_interest(ticks.ticks_ms()) == IO_WRITE

    def test_io_interest_read_only_during_receive(self):
        socket = FakeSocket()
        # Stall the recv so the request stays in RECEIVING.  An empty
        # recv queue with no queued eagains would be a clean peer close
        # and would fail the request rather than stall.
        socket.enqueue_eagain_for_recv(99)
        client, ticks, _ = make_client(socket_or_factory=socket)
        client.get("http://example.test/")
        # First handle ticks the connector through dns_ok; second
        # through tcp_ok → promote → SENDING → drain → RECEIVING.
        client.handle(ticks.ticks_ms())
        client.handle(ticks.ticks_ms())

        assert client.io_interest(ticks.ticks_ms()) == IO_READ

    def test_next_deadline_none_when_idle(self):
        client, ticks, _ = make_client()
        assert client.next_deadline(ticks.ticks_ms()) is None

    def test_next_deadline_clamps_to_now_while_awaiting_dns(self):
        """At request start the connector is in awaiting_dns with no
        socket, so io_socket is None and next_deadline collapses to
        now_ms — Runner.wait then ticks the connector forward instead
        of sleeping toward the far request deadline."""
        socket = FakeSocket()
        client, ticks, _ = make_client(
            socket_or_factory=socket, default_timeout_ms=500,
        )
        client.get("http://example.test/")

        assert client.io_socket is None
        assert client.next_deadline(777) == 777

    def test_next_deadline_returns_request_deadline_once_pollable(self):
        """Once one handle tick drives dns_ok and the connector exposes
        its socket, the clamp lifts and the per-request budget (500 ms
        from start) governs the wake again."""
        socket = FakeSocket()
        client, ticks, _ = make_client(
            socket_or_factory=socket, default_timeout_ms=500,
        )
        start = ticks.ticks_ms()
        client.get("http://example.test/")
        # Drive the connector one step: dns_ok makes io_socket live.
        client.handle(ticks.ticks_ms())

        assert client.io_socket is socket
        deadline = client.next_deadline(ticks.ticks_ms())
        assert deadline is not None
        assert ticks.ticks_diff(deadline, start) == 500

    def test_io_attributes_clear_after_request_completes(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"ok"))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        assert client.io_socket is None
        assert client.io_interest(ticks.ticks_ms()) == 0
        assert client.next_deadline(ticks.ticks_ms()) is None

    def test_runner_wait_registers_socket_for_writing_then_reading(self):
        """End-to-end: a request drives register(POLLOUT) on the first
        wait, modify to POLLIN once SENDING completes, then unregister
        when the request returns to IDLE."""
        socket = FakeSocket()
        # One send EAGAIN keeps SENDING visible for one wait() call
        # before the buffer drains; one recv EAGAIN keeps RECEIVING
        # visible for one wait() call before the body arrives.
        socket.enqueue_eagain_for_send(1)
        socket.enqueue_eagain_for_recv(1)
        socket.enqueue_recv(canned_response(body=b"ok"))
        ticks = FakeTicks()
        poller = FakePoller()
        runner = Runner(ticks=ticks, poller=poller)
        client = HttpClient(
            transport_factory=make_factory(socket), ticks=ticks,
        )
        runner.add(client)

        handle = client.get("http://example.test/")
        # Fire wait once before the first tick so wait observes the
        # initial SENDING state set by client.get(); then drive
        # tick / wait until the response is decoded.
        runner.wait(ticks.ticks_ms())
        for _ in range(40):
            now_ms = runner.tick()
            runner.wait(now_ms)
            if handle.done:
                break
            ticks.advance(1)

        assert handle.done is True
        # SENDING phase asked for POLLOUT.
        assert any(
            eventmask == select.POLLOUT
            for _sock, eventmask in poller.register_calls + poller.modify_calls
        )
        # RECEIVING phase asked for POLLIN.
        assert any(
            eventmask == select.POLLIN
            for _sock, eventmask in poller.register_calls + poller.modify_calls
        )
        # Completion unregistered the socket.
        assert socket in poller.unregister_calls
