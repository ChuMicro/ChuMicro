"""End-to-end integration tests for chumicro_websockets — slice 4.

Wires a :class:`WebSocketClient` and a :class:`WebSocketServer` together
in-process via paired :class:`FakeConnection` objects.  Bytes the
client writes get pumped into the server's inbound queue between
ticks, and vice versa — a complete client ↔ server loopback that
drives both state machines through the runner contract without any
real sockets.

Proves the slice 1/2/3 components fit together:

* The client-side handshake produces bytes the server's
  :class:`HandshakeRequestParser` accepts; the server's 101 response
  is what the client's :class:`HandshakeResponseParser` validates
  against the derived accept token.
* Client outbound mask discipline (clients MUST mask) is exactly
  what the server's mask validator requires (and vice versa).
* Frame parsing + reassembly + UTF-8 validation works end-to-end.
* Close handshake initiated from either side completes cleanly.
* Bidirectional traffic in the same tick survives intact.
"""

from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    CLOSE_GOING_AWAY,
    CLOSE_NORMAL,
    WebSocketClient,
    WebSocketServer,
    WebSocketState,
)
from chumicro_websockets.testing import FakeConnection, FakeListener


def _pump(client_socket: FakeConnection, server_socket: FakeConnection) -> None:
    """Move bytes both directions: client.outbound -> server.inbound + reverse."""
    if client_socket.outbound:
        server_socket.feed_inbound(bytes(client_socket.outbound))
        client_socket.outbound = bytearray()
    if server_socket.outbound:
        client_socket.feed_inbound(bytes(server_socket.outbound))
        server_socket.outbound = bytearray()


def _build_loopback_pair(*, on_connection):
    """Return ``(client, server, client_socket, server_socket, clock)``.

    Both halves share a FakeTicks; the client's connection_factory
    returns the client-side FakeConnection; the server's listener
    will hand out the server-side FakeConnection on accept.
    """
    clock = FakeTicks()
    client_socket = FakeConnection()
    server_socket = FakeConnection()
    listener = FakeListener()
    listener.queue_accept(server_socket)

    server = WebSocketServer(
        listener=listener,
        on_connection=on_connection,
        ticks=clock,
    )
    client = WebSocketClient(
        connection_factory=lambda *_args, **_kwargs: client_socket,
        ticks=clock,
    )
    return client, server, client_socket, server_socket, clock


def _drive_both_to_open(
    client: WebSocketClient,
    server: WebSocketServer,
    client_socket: FakeConnection,
    server_socket: FakeConnection,
    clock: FakeTicks,
    *,
    max_ticks: int = 50,
) -> None:
    """Pump both sides until the client reaches OPEN.  Asserts handshake completed."""
    client.connect("ws://example.com/")
    for _tick in range(max_ticks):
        client.handle(clock.ticks_ms())
        server.handle(clock.ticks_ms())
        _pump(client_socket, server_socket)
        if client.state == WebSocketState.OPEN:
            break
    assert client.state == WebSocketState.OPEN
    assert server.connection_count == 1
    assert server.connections[0].state == WebSocketState.OPEN


def _drive_until(
    client: WebSocketClient,
    server: WebSocketServer,
    client_socket: FakeConnection,
    server_socket: FakeConnection,
    clock: FakeTicks,
    predicate,
    *,
    max_ticks: int = 50,
) -> None:
    """Pump both sides until *predicate()* returns truthy."""
    for _tick in range(max_ticks):
        client.handle(clock.ticks_ms())
        server.handle(clock.ticks_ms())
        _pump(client_socket, server_socket)
        if predicate():
            return
    raise AssertionError(
        f"predicate did not become true within {max_ticks} ticks; "
        f"client.state={client.state}, "
        f"server.connection_count={server.connection_count}",
    )


# ---------------------------------------------------------------------------
# Handshake
# ---------------------------------------------------------------------------


class TestHandshake:
    def test_full_handshake_loopback(self):
        observed_server = []
        observed_client_open = []

        def on_connection(connection):
            observed_server.append(connection)

        client, server, client_socket, server_socket, clock = (
            _build_loopback_pair(on_connection=on_connection)
        )
        client.on_open = lambda: observed_client_open.append(True)
        _drive_both_to_open(client, server, client_socket, server_socket, clock)
        assert observed_client_open == [True]
        assert len(observed_server) == 1
        assert observed_server[0].request_path == "/"


# ---------------------------------------------------------------------------
# Bidirectional data
# ---------------------------------------------------------------------------


class TestBidirectionalData:
    def test_client_to_server_text(self):
        received = []

        def on_connection(connection):
            connection.on_text = lambda text: received.append(text)

        client, server, client_socket, server_socket, clock = (
            _build_loopback_pair(on_connection=on_connection)
        )
        _drive_both_to_open(client, server, client_socket, server_socket, clock)
        client.send_text("hello server")
        _drive_until(
            client, server, client_socket, server_socket, clock,
            lambda: bool(received),
        )
        assert received == ["hello server"]

    def test_server_to_client_text(self):
        observed_server = []

        def on_connection(connection):
            observed_server.append(connection)

        received = []
        client, server, client_socket, server_socket, clock = (
            _build_loopback_pair(on_connection=on_connection)
        )
        client.on_text = lambda text: received.append(text)
        _drive_both_to_open(client, server, client_socket, server_socket, clock)
        observed_server[0].send_text("hello client")
        _drive_until(
            client, server, client_socket, server_socket, clock,
            lambda: bool(received),
        )
        assert received == ["hello client"]

    def test_binary_round_trip(self):
        observed_server = []
        client_received = []
        server_received = []

        def on_connection(connection):
            observed_server.append(connection)
            connection.on_binary = lambda data: server_received.append(data)

        client, server, client_socket, server_socket, clock = (
            _build_loopback_pair(on_connection=on_connection)
        )
        client.on_binary = lambda data: client_received.append(data)
        _drive_both_to_open(client, server, client_socket, server_socket, clock)
        client.send_binary(b"\x00\x01\x02")
        observed_server[0].send_binary(b"\x10\x11\x12")
        _drive_until(
            client, server, client_socket, server_socket, clock,
            lambda: bool(client_received) and bool(server_received),
        )
        assert client_received == [b"\x10\x11\x12"]
        assert server_received == [b"\x00\x01\x02"]

    def test_echo_pattern(self):
        observed_server = []
        client_received = []

        def on_connection(connection):
            observed_server.append(connection)
            connection.on_text = lambda text: connection.send_text(f"echo: {text}")

        client, server, client_socket, server_socket, clock = (
            _build_loopback_pair(on_connection=on_connection)
        )
        client.on_text = lambda text: client_received.append(text)
        _drive_both_to_open(client, server, client_socket, server_socket, clock)
        client.send_text("ping")
        _drive_until(
            client, server, client_socket, server_socket, clock,
            lambda: bool(client_received),
        )
        assert client_received == ["echo: ping"]


# ---------------------------------------------------------------------------
# Ping / pong
# ---------------------------------------------------------------------------


class TestPingPong:
    def test_client_ping_server_auto_pong(self):
        observed_server_pings = []

        def on_connection(connection):
            connection.on_ping = lambda payload: observed_server_pings.append(payload)

        pongs = []
        client, server, client_socket, server_socket, clock = (
            _build_loopback_pair(on_connection=on_connection)
        )
        client.on_pong = lambda payload: pongs.append(payload)
        _drive_both_to_open(client, server, client_socket, server_socket, clock)
        client.send_ping(b"heartbeat")
        _drive_until(
            client, server, client_socket, server_socket, clock,
            lambda: bool(pongs),
        )
        assert observed_server_pings == [b"heartbeat"]
        assert pongs == [b"heartbeat"]

    def test_server_ping_client_auto_pong(self):
        observed_server = []
        observed_client_pings = []

        def on_connection(connection):
            observed_server.append(connection)

        client, server, client_socket, server_socket, clock = (
            _build_loopback_pair(on_connection=on_connection)
        )
        client.on_ping = lambda payload: observed_client_pings.append(payload)
        observed_server_pongs = []
        _drive_both_to_open(client, server, client_socket, server_socket, clock)
        observed_server[0].on_pong = lambda payload: observed_server_pongs.append(payload)
        observed_server[0].send_ping(b"server-hb")
        _drive_until(
            client, server, client_socket, server_socket, clock,
            lambda: bool(observed_server_pongs),
        )
        assert observed_client_pings == [b"server-hb"]
        assert observed_server_pongs == [b"server-hb"]


# ---------------------------------------------------------------------------
# Close handshake
# ---------------------------------------------------------------------------


class TestCloseHandshake:
    def test_client_initiated_close(self):
        observed_server = []
        observed_server_closes = []

        def on_connection(connection):
            observed_server.append(connection)
            connection.on_close = lambda code, reason: (
                observed_server_closes.append((code, reason))
            )

        client_closes = []
        client, server, client_socket, server_socket, clock = (
            _build_loopback_pair(on_connection=on_connection)
        )
        client.on_close = lambda code, reason: client_closes.append((code, reason))
        _drive_both_to_open(client, server, client_socket, server_socket, clock)
        client.close(CLOSE_GOING_AWAY, "client done")
        _drive_until(
            client, server, client_socket, server_socket, clock,
            lambda: (
                client.state == WebSocketState.CLOSED
                and observed_server[0].state == WebSocketState.CLOSED
            ),
        )
        assert client.state == WebSocketState.CLOSED
        assert observed_server[0].state == WebSocketState.CLOSED
        assert client_closes == [(CLOSE_GOING_AWAY, "client done")]
        # Server's on_close fires with the peer-supplied code+reason.
        assert observed_server_closes == [(CLOSE_GOING_AWAY, "client done")]

    def test_server_initiated_close(self):
        observed_server = []
        observed_server_closes = []

        def on_connection(connection):
            observed_server.append(connection)
            connection.on_close = lambda code, reason: (
                observed_server_closes.append((code, reason))
            )

        client_closes = []
        client, server, client_socket, server_socket, clock = (
            _build_loopback_pair(on_connection=on_connection)
        )
        client.on_close = lambda code, reason: client_closes.append((code, reason))
        _drive_both_to_open(client, server, client_socket, server_socket, clock)
        observed_server[0].close(CLOSE_NORMAL, "server done")
        _drive_until(
            client, server, client_socket, server_socket, clock,
            lambda: (
                client.state == WebSocketState.CLOSED
                and observed_server[0].state == WebSocketState.CLOSED
            ),
        )
        assert client.state == WebSocketState.CLOSED
        assert observed_server[0].state == WebSocketState.CLOSED
        assert observed_server_closes == [(CLOSE_NORMAL, "server done")]
        assert client_closes == [(CLOSE_NORMAL, "server done")]


# ---------------------------------------------------------------------------
# Concurrent traffic
# ---------------------------------------------------------------------------


class TestConcurrentTraffic:
    def test_simultaneous_send_both_directions(self):
        observed_server = []
        client_received = []
        server_received = []

        def on_connection(connection):
            observed_server.append(connection)
            connection.on_text = lambda text: server_received.append(text)

        client, server, client_socket, server_socket, clock = (
            _build_loopback_pair(on_connection=on_connection)
        )
        client.on_text = lambda text: client_received.append(text)
        _drive_both_to_open(client, server, client_socket, server_socket, clock)
        # Both sides queue messages before any tick runs.
        for index in range(3):
            client.send_text(f"client-{index}")
            observed_server[0].send_text(f"server-{index}")
        _drive_until(
            client, server, client_socket, server_socket, clock,
            lambda: len(client_received) == 3 and len(server_received) == 3,
        )
        assert client_received == ["server-0", "server-1", "server-2"]
        assert server_received == ["client-0", "client-1", "client-2"]
