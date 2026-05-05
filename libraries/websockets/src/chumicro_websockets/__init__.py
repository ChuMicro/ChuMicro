"""Non-blocking WebSocket client + server for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  No async, no threads — a tick-based runner contract: both
:class:`WebSocketClient` and :class:`WebSocketServer` satisfy
``check(now_ms) -> bool`` + ``handle(now_ms)``.  The canonical
promise: an LED can keep blinking on the same board through the
opening handshake, frame I/O, control-frame interleave, and the
close handshake.

Public API::

    from chumicro_websockets import WebSocketClient, WebSocketState

    def make_socket(host, port, use_tls):
        from chumicro_sockets import tcp_client_socket
        return tcp_client_socket(host, port)

    client = WebSocketClient(connection_factory=make_socket)
    client.on_text = lambda text: print(text)
    client.connect("ws://api.example.com/stream")

    while client.state != WebSocketState.CLOSED:
        if client.check(now_ms()):
            client.handle(now_ms())

Implementation detail (frame encoders, handshake parsers, the case-
insensitive header dict, spec-trivia close codes, oversize policy
internals) lives in :mod:`chumicro_websockets._wire` and is reached
from there in tests + advanced users — keeping the top-level surface
tight saves flash + parse-time RAM on the device.
"""

from chumicro_websockets._wire import (
    CLOSE_BAD_DATA,
    CLOSE_GOING_AWAY,
    CLOSE_INTERNAL_ERROR,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    CLOSE_TOO_BIG,
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_CONTINUATION,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    WebSocketBackpressureError,
    WebSocketError,
    WebSocketHandshakeError,
    WebSocketOversizedError,
    WebSocketProtocolError,
    WebSocketState,
    WebSocketStateError,
    WebSocketTimeoutError,
    WebSocketURLError,
    derive_accept_key,
    make_websocket_key,
    parse_ws_url,
)
from chumicro_websockets.client import WebSocketClient, WhenOversized
from chumicro_websockets.server import Connection, WebSocketServer

__all__ = [
    "CLOSE_BAD_DATA",
    "CLOSE_GOING_AWAY",
    "CLOSE_INTERNAL_ERROR",
    "CLOSE_NORMAL",
    "CLOSE_PROTOCOL_ERROR",
    "CLOSE_TOO_BIG",
    "OPCODE_BINARY",
    "OPCODE_CLOSE",
    "OPCODE_CONTINUATION",
    "OPCODE_PING",
    "OPCODE_PONG",
    "OPCODE_TEXT",
    "Connection",
    "WebSocketBackpressureError",
    "WebSocketClient",
    "WebSocketError",
    "WebSocketHandshakeError",
    "WebSocketOversizedError",
    "WebSocketProtocolError",
    "WebSocketServer",
    "WebSocketState",
    "WebSocketStateError",
    "WebSocketTimeoutError",
    "WebSocketURLError",
    "WhenOversized",
    "derive_accept_key",
    "make_websocket_key",
    "parse_ws_url",
]
