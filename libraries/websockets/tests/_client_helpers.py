"""Shared helpers for the WebSocket client test files (not a test module).

Factory / handshake-drive / frame-encode helpers used across several
``test_client_*.py`` files.  Underscore-prefixed so pytest never
collects it; the tests' own directory is on ``sys.path`` on host,
unix-port, and device, so ``from _client_helpers import ...`` resolves
in every lane.
"""

from chumicro_sockets.testing import FakeSocketConnector
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    WebSocketClient,
    WebSocketState,
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
    """Push ticks until AWAITING_TRANSPORT + SENDING_HANDSHAKE finish, then craft + feed a 101.

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
        transport_factory=factory,
        ticks=clock,
        **kwargs,
    )
    return client, socket, clock, record

def _client_frame(opcode: int, payload: bytes) -> bytes:
    """Encode a server→client frame (no mask) for inbound feeding."""
    return encode_frame(opcode, payload, fin=True, mask=None)
