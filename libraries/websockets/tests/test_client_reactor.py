"""WebSocket client tests (chumicro_websockets.client): the
Runner/reactor contract — io_socket, io_interest, next_deadline."""

import select

from _client_helpers import (
    FakeSocket,
    _drive_handshake,
    _make_client,
    _make_factory,
)
from chumicro_runner import IO_READ, IO_WRITE, Runner
from chumicro_runner.testing import FakePoller
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    WebSocketClient,
    WebSocketState,
)
from chumicro_websockets.client import ConnectingPhase


class TestRunnerReactorContract:
    """``io_socket`` / ``io_interest`` / ``next_deadline`` let
    ``Runner.wait`` register the websocket socket and idle the loop
    until readiness or the next deadline fires."""

    def test_io_socket_none_before_connect(self):
        client, _socket, _clock, _ = _make_client()
        assert client.io_socket is None

    def test_io_socket_returns_socket_while_connecting(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        # At ``awaiting_dns`` the connector has not built its socket, so
        # the pollable is ``None``; one ``handle`` drives ``dns_ok`` and
        # the connector's socket goes live.
        assert client.io_socket is None
        client.handle(clock.ticks_ms())
        # FakeConnection has no ``_sock`` wrapper, so the property
        # returns it directly.
        assert client.io_socket is socket

    def test_io_socket_none_once_closed(self):
        client, _socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, _socket, clock)
        client._finalize_closed()  # force CLOSED
        assert client.io_socket is None

    def test_io_socket_returns_adapter_wrapper_as_is(self):
        # After the MP adapter promotes the connector's socket to an
        # _MpSocketWrapper-style object whose pollable lives on ``.sock``,
        # io_socket returns that wrapper unchanged.  The runner unwraps
        # the ``.sock`` pollable at the poller, so the client hands back
        # its socket-ish object without inspecting it.
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)

        class _AdapterWrapper:
            def __init__(self, sock):
                self.sock = sock

        wrapper = _AdapterWrapper(socket)
        client._socket = wrapper
        assert client.io_socket is wrapper

    def test_io_interest_write_during_sending_handshake(self):
        client, _socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        # Drive past AWAITING_TRANSPORT (dns_ok + tcp_ok) so the
        # client lands in SENDING_HANDSHAKE.
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        assert client._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE
        assert client.io_interest(clock.ticks_ms()) == IO_WRITE

    def test_io_interest_read_during_receiving_handshake(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        # Drain the upgrade-request send.
        while client._connecting_phase in (
            ConnectingPhase.AWAITING_TRANSPORT, ConnectingPhase.SENDING_HANDSHAKE,
        ):
            client.handle(clock.ticks_ms())
        assert client._connecting_phase == ConnectingPhase.RECEIVING_HANDSHAKE
        assert client.io_interest(clock.ticks_ms()) == IO_READ

    def test_io_interest_read_when_open(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        assert client.state == WebSocketState.OPEN
        assert client.io_interest(clock.ticks_ms()) == IO_READ

    def test_io_interest_write_tracks_tx_queue_when_open(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        # Empty queue: read interest only.
        assert client.io_interest(clock.ticks_ms()) == IO_READ

        client.send_text("hello")
        assert client.io_interest(clock.ticks_ms()) == IO_READ | IO_WRITE

        # Drive once to drain.
        client.handle(clock.ticks_ms())
        assert client.io_interest(clock.ticks_ms()) == IO_READ

    def test_next_deadline_clamps_to_now_while_awaiting_dns(self):
        """At connect the connector is in awaiting_dns with no socket,
        so io_socket is None and next_deadline collapses to now_ms —
        Runner.wait ticks the connector forward instead of sleeping
        toward the far handshake-timeout deadline."""
        client, _socket, _clock, _ = _make_client(
            handshake_timeout_ms=3000,
        )
        client.connect("ws://example.com/")
        assert client.io_socket is None
        assert client.next_deadline(777) == 777

    def test_next_deadline_returns_handshake_deadline_once_pollable(self):
        """Once one handle tick drives dns_ok and the connector exposes
        its socket, the clamp lifts and the handshake-timeout deadline
        (3000 ms from start) governs the wake again."""
        client, _socket, clock, _ = _make_client(
            handshake_timeout_ms=3000,
        )
        start = clock.ticks_ms()
        client.connect("ws://example.com/")
        # Drive the connector one step: dns_ok makes io_socket live.
        client.handle(clock.ticks_ms())
        assert client.io_socket is not None
        deadline = client.next_deadline(clock.ticks_ms())
        assert deadline is not None
        assert clock.ticks_diff(deadline, start) == 3000

    def test_next_deadline_none_when_idle_and_open(self):
        """OPEN with no auto-ping configured and no pending pong has no deadline."""
        client, socket, clock, _ = _make_client()  # ping_interval_ms defaults to None
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        assert client.next_deadline(clock.ticks_ms()) is None

    def test_runner_wait_registers_socket_for_handshake_then_open(self):
        """End-to-end: connect() registers POLLOUT during AWAITING_TRANSPORT
        (the connector's TCP-connect phase wants writability), keeps it
        through SENDING_HANDSHAKE, modifies to POLLIN once the request
        bytes drain, and OPEN stays registered for POLLIN."""
        socket = FakeSocket()
        clock = FakeTicks()
        poller = FakePoller()
        runner = Runner(ticks=clock, poller=poller)
        factory, _record = _make_factory(socket)
        client = WebSocketClient(transport_factory=factory, ticks=clock)
        runner.add(client)

        client.connect("ws://example.com/")
        # Connector starts in awaiting_dns where io_interest has no
        # write bit; one tick advances to awaiting_tcp where the runner
        # parks on POLLOUT.
        runner.tick()
        runner.wait(clock.ticks_ms())
        first_marks = poller.register_calls
        assert any(
            eventmask & select.POLLOUT
            for _sock, eventmask in first_marks
        )

        _drive_handshake(client, socket, clock)
        # Now OPEN with empty tx queue -> POLLIN only on the next wait.
        runner.wait(clock.ticks_ms())
        last_event = (
            poller.modify_calls[-1]
            if poller.modify_calls
            else poller.register_calls[-1]
        )
        _last_sock, last_mask = last_event
        assert last_mask == select.POLLIN
