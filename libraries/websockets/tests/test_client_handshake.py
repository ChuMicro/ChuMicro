"""WebSocket client tests (chumicro_websockets.client): constructor,
connect, opening-handshake send/receive."""

import errno
import select

from chumicro_runner import Runner
from chumicro_runner.testing import FakePoller
from chumicro_sockets.testing import FakeSocketConnector
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    CLOSE_INTERNAL_ERROR,
    OPCODE_TEXT,
    WebSocketClient,
    WebSocketHandshakeError,
    WebSocketState,
    WebSocketStateError,
    WebSocketURLError,
    derive_accept_key,
)
from chumicro_websockets._wire import (
    HandshakeRequestParser,
    encode_frame,
)
from chumicro_websockets.client import ConnectingPhase
from chumicro_websockets.testing import FakeConnection

FakeSocket = FakeConnection

def _make_factory(socket: FakeConnection, *, expected_use_tls: bool | None = None):
    """Connector-factory closure that records its args + returns a
    scripted ``FakeSocketConnector`` wrapping *socket*."""
    record = {"calls": []}

    def factory(host, port, use_tls):
        record["calls"].append((host, port, use_tls))
        if expected_use_tls is not None:
            assert use_tls is expected_use_tls
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=socket)

    return factory, record

def _drive_handshake(
    client: WebSocketClient,
    socket: FakeSocket,
    clock: FakeTicks,
) -> bytes:
    """Push ticks until SENDING_HANDSHAKE finishes, then craft + feed a 101.

    Returns the request bytes the client wrote so callers can assert on
    them (``Sec-WebSocket-Key`` etc.).  Leaves the client OPEN.
    """
    # Drain AWAITING_TRANSPORT (connector ticks) + SENDING_HANDSHAKE.
    while client.state == WebSocketState.CONNECTING and (
        client._connecting_phase
        in (ConnectingPhase.AWAITING_TRANSPORT, ConnectingPhase.SENDING_HANDSHAKE)
    ):
        client.handle(clock.ticks_ms())
    request_bytes = socket.read_outbound()
    # Parse the request to get the client's key.
    parser = HandshakeRequestParser()
    parser.feed(request_bytes)
    accept_token = derive_accept_key(parser.client_key)
    response = (
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: " + accept_token.encode("ascii") + b"\r\n"
        b"\r\n"
    )
    socket.feed_inbound(response)
    # Drive once to consume + transition to OPEN.
    client.handle(clock.ticks_ms())
    return request_bytes

def _make_client(
    *,
    socket: FakeSocket | None = None,
    clock: FakeTicks | None = None,
    **kwargs,
):
    """Construct a client wired to a fresh fake socket + clock."""
    if socket is None:
        socket = FakeSocket()
    if clock is None:
        clock = FakeTicks()
    factory, record = _make_factory(socket)
    client = WebSocketClient(
        connector_factory=factory,
        ticks=clock,
        **kwargs,
    )
    return client, socket, clock, record

def _client_frame(opcode: int, payload: bytes) -> bytes:
    """Encode a server→client frame (no mask) for inbound feeding."""
    return encode_frame(opcode, payload, fin=True, mask=None)


class TestConstructor:
    def test_initial_state_is_connecting(self):
        client, _socket, _clock, _ = _make_client()
        assert client.state == WebSocketState.CONNECTING

    def test_state_url_close_fields_blank_pre_connect(self):
        client, _socket, _clock, _ = _make_client()
        assert client.url == ""
        assert client.last_close_code is None
        assert client.last_close_reason == ""
        assert client.last_error is None

    def test_check_pre_connect_returns_false(self):
        client, _socket, clock, _ = _make_client()
        assert client.check(clock.ticks_ms()) is False

    def test_handle_pre_connect_is_noop(self):
        client, socket, clock, _ = _make_client()
        client.handle(clock.ticks_ms())
        assert socket.read_outbound() == b""


class TestConnect:
    def test_invokes_factory_with_parsed_url(self):
        client, _socket, _clock, record = _make_client()
        client.connect("ws://api.example.com:8080/socket?q=1")
        assert record["calls"] == [("api.example.com", 8080, False)]
        assert client.url == "ws://api.example.com:8080/socket?q=1"

    def test_wss_passes_use_tls_true(self):
        socket = FakeSocket()
        clock = FakeTicks()
        factory, record = _make_factory(socket, expected_use_tls=True)
        client = WebSocketClient(
            connector_factory=factory,
            ticks=clock,
        )
        client.connect("wss://secure.example.com/")
        assert record["calls"] == [("secure.example.com", 443, True)]

    def test_url_must_be_ws_or_wss(self):
        client, _socket, _clock, _ = _make_client()
        with raises(WebSocketURLError):
            client.connect("http://example.com/")

    def test_close_during_connecting_cancels_connector_and_finalizes(self):
        # Aborting a slow connect (state CONNECTING, no socket yet) must
        # not queue a CLOSE frame it can never send — the next handle()
        # would then recv_into a None socket.  Finalize directly and
        # cancel the in-flight connector so its socket does not leak.
        clock = FakeTicks()
        captured = {}

        def factory(host, port, use_tls):
            connector = FakeSocketConnector(actions=[], socket=FakeSocket())
            captured["connector"] = connector
            return connector

        client = WebSocketClient(connector_factory=factory, ticks=clock)
        client.connect("ws://example.com/")
        client.handle(clock.ticks_ms())  # AWAITING_TRANSPORT, connector idle
        assert client._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT
        client.close()
        assert client.state == WebSocketState.CLOSED
        assert captured["connector"].state == "failed"  # cancel() fired
        assert client.io_socket is None
        client.handle(clock.ticks_ms())  # no crash: CLOSED short-circuits

    def test_handshake_timeout_during_connecting_cancels_connector(self):
        # A handshake-deadline expiry while still AWAITING_TRANSPORT must
        # cancel the in-flight connector (its half-open socket would
        # otherwise leak) and stop io_socket forwarding to it.
        clock = FakeTicks()
        captured = {}

        def factory(host, port, use_tls):
            connector = FakeSocketConnector(actions=[], socket=FakeSocket())
            captured["connector"] = connector
            return connector

        client = WebSocketClient(
            connector_factory=factory, ticks=clock, handshake_timeout_ms=1000,
        )
        client.connect("ws://example.com/")
        client.handle(clock.ticks_ms())
        clock.advance(1500)  # past the handshake deadline
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert captured["connector"].state == "failed"
        assert client.io_socket is None

    def test_double_connect_raises(self):
        client, _socket, _clock, _ = _make_client()
        client.connect("ws://example.com/")
        with raises(WebSocketStateError, match="only be called once"):
            client.connect("ws://other.example.com/")

    def test_state_is_connecting_after_connect(self):
        client, _socket, _clock, _ = _make_client()
        client.connect("ws://example.com/")
        assert client.state == WebSocketState.CONNECTING

    def test_check_after_connect_returns_true(self):
        client, _socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        assert client.check(clock.ticks_ms()) is True


class TestHandshakeSend:
    def test_handle_pushes_request_bytes(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        client.handle(clock.ticks_ms())  # dns_ok
        client.handle(clock.ticks_ms())  # tcp_ok → ready → SENDING_HANDSHAKE
        client.handle(clock.ticks_ms())  # send handshake bytes
        outbound = socket.peek_outbound()
        assert outbound.startswith(b"GET / HTTP/1.1\r\n")
        assert b"Upgrade: websocket\r\n" in outbound
        assert b"Sec-WebSocket-Version: 13\r\n" in outbound

    def test_send_chunked_completes_across_ticks(self):
        socket = FakeSocket()
        socket.send_chunk_cap = 16  # only 16 bytes per send
        client, _socket, clock, _ = _make_client(socket=socket)
        client.connect("ws://example.com/")
        # Multiple handles needed to drain AWAITING_TRANSPORT + handshake send.
        seen_phases = []
        for _tick in range(40):
            seen_phases.append(client._connecting_phase)
            if client._connecting_phase not in (
                ConnectingPhase.AWAITING_TRANSPORT, ConnectingPhase.SENDING_HANDSHAKE,
            ):
                break
            client.handle(clock.ticks_ms())
        assert client._connecting_phase == ConnectingPhase.RECEIVING_HANDSHAKE

    def test_eagain_during_send_keeps_state(self):
        socket = FakeSocket()
        socket.raise_on_send = OSError(errno.EAGAIN, "would block")
        client, _socket, clock, _ = _make_client(socket=socket)
        client.connect("ws://example.com/")
        # First two ticks drive the connector through dns_ok + tcp_ok;
        # third tick attempts the handshake send and hits EAGAIN.
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        # State unchanged.  No bytes were consumed.
        assert client.state == WebSocketState.CONNECTING
        assert client._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE

    def test_send_error_transitions_to_closed(self):
        socket = FakeSocket()
        socket.raise_on_send = OSError(99, "socket dead")
        client, _socket, clock, _ = _make_client(socket=socket)
        closes = []
        client.on_close = lambda code, reason: closes.append((code, reason))
        client.connect("ws://example.com/")
        # Connector phases first, then the send raises a fatal OSError.
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert isinstance(client.last_error, WebSocketHandshakeError)
        assert closes == [(CLOSE_INTERNAL_ERROR, str(client.last_error))]


class TestHandshakeReceive:
    def test_valid_response_transitions_to_open(self):
        client, socket, clock, _ = _make_client()
        opens = []
        client.on_open = lambda: opens.append("open")
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        assert client.state == WebSocketState.OPEN
        assert opens == ["open"]

    def test_invalid_status_transitions_to_closed(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        # Drain SEND phase first.
        while client._connecting_phase in (
            ConnectingPhase.AWAITING_TRANSPORT, ConnectingPhase.SENDING_HANDSHAKE,
        ):
            client.handle(clock.ticks_ms())
        socket.read_outbound()
        socket.feed_inbound(
            b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n",
        )
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert isinstance(client.last_error, WebSocketHandshakeError)

    def test_peer_eof_mid_handshake_is_failure(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        while client._connecting_phase in (
            ConnectingPhase.AWAITING_TRANSPORT, ConnectingPhase.SENDING_HANDSHAKE,
        ):
            client.handle(clock.ticks_ms())
        socket.close_inbound()
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CLOSED
        assert isinstance(client.last_error, WebSocketHandshakeError)
        assert "mid-handshake" in str(client.last_error)

    def test_eagain_during_receive_keeps_state(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        while client._connecting_phase in (
            ConnectingPhase.AWAITING_TRANSPORT, ConnectingPhase.SENDING_HANDSHAKE,
        ):
            client.handle(clock.ticks_ms())
        # No inbound bytes, no EOF.  recv_into raises EAGAIN.
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.CONNECTING

    def test_leftover_bytes_flow_into_frame_parser(self):
        client, socket, clock, _ = _make_client()
        opens = []
        client.on_open = lambda: opens.append("open")
        texts = []
        client.on_text = lambda text: texts.append(text)
        client.connect("ws://example.com/")
        # Drive handshake send.
        while client._connecting_phase in (
            ConnectingPhase.AWAITING_TRANSPORT, ConnectingPhase.SENDING_HANDSHAKE,
        ):
            client.handle(clock.ticks_ms())
        request = socket.read_outbound()
        parser = HandshakeRequestParser()
        parser.feed(request)
        accept = derive_accept_key(parser.client_key)
        # Piggyback a TEXT frame after the response terminator.
        socket.feed_inbound(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept.encode("ascii") + b"\r\n\r\n"
            + _client_frame(OPCODE_TEXT, b"hello"),
        )
        client.handle(clock.ticks_ms())
        assert client.state == WebSocketState.OPEN
        assert opens == ["open"]
        assert texts == ["hello"]

    def test_extra_headers_appear_in_request(self):
        client, socket, clock, _ = _make_client()
        client.connect(
            "ws://example.com/",
            extra_headers={"Origin": "https://app.example.com"},
        )
        # Drive past AWAITING_TRANSPORT + send the handshake bytes.
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        outbound = socket.peek_outbound()
        assert b"Origin: https://app.example.com\r\n" in outbound


class TestRunnerReactorContract:
    """``io_socket`` / ``io_wants_read`` / ``io_wants_write`` /
    ``next_deadline`` let ``Runner.wait`` register the websocket socket
    and idle the loop until readiness or the next deadline fires."""

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

    def test_io_wants_write_during_sending_handshake(self):
        client, _socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        # Drive past AWAITING_TRANSPORT (dns_ok + tcp_ok) so the
        # client lands in SENDING_HANDSHAKE.
        client.handle(clock.ticks_ms())
        client.handle(clock.ticks_ms())
        assert client._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE
        assert client.io_wants_write is True
        assert client.io_wants_read is False

    def test_io_wants_read_during_receiving_handshake(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        # Drain the upgrade-request send.
        while client._connecting_phase in (
            ConnectingPhase.AWAITING_TRANSPORT, ConnectingPhase.SENDING_HANDSHAKE,
        ):
            client.handle(clock.ticks_ms())
        assert client._connecting_phase == ConnectingPhase.RECEIVING_HANDSHAKE
        assert client.io_wants_read is True
        assert client.io_wants_write is False

    def test_io_wants_read_when_open(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        assert client.state == WebSocketState.OPEN
        assert client.io_wants_read is True

    def test_io_wants_write_tracks_tx_queue_when_open(self):
        client, socket, clock, _ = _make_client()
        client.connect("ws://example.com/")
        _drive_handshake(client, socket, clock)
        # Empty queue.
        assert client.io_wants_write is False

        client.send_text("hello")
        assert client.io_wants_write is True

        # Drive once to drain.
        client.handle(clock.ticks_ms())
        assert client.io_wants_write is False

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
        client = WebSocketClient(connector_factory=factory, ticks=clock)
        runner.add(client)

        client.connect("ws://example.com/")
        # Connector starts in awaiting_dns where io_wants_write is
        # False; one tick advances to awaiting_tcp where the runner
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
