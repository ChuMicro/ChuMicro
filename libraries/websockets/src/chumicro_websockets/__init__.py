"""``chumicro_websockets`` runs WebSocket clients and servers one non-blocking step at a time.

A WebSocket (RFC 6455) is a TCP connection that stays open, so either end can
send a message at any time.  The connection opens with the opening handshake,
an HTTP request that the server answers with ``101 Switching Protocols``.
After that, each message travels as one or more frames.  A frame is a short
header plus a payload.  The opcode in the header marks the frame as text,
binary data, or a control frame: CLOSE, PING, or PONG.

``WebSocketClient`` connects to a server.  ``WebSocketServer`` accepts
clients and hands each one over as a ``Connection``.  The ``CLOSE_*``
constants name the status codes that ``close()`` sends and ``on_close``
receives.  The ``OPCODE_*`` constants name the frame opcodes.
"""

import gc

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
    WebSocketProtocolError,
    WebSocketState,
    WebSocketStateError,
    WebSocketTimeoutError,
    WebSocketURLError,
    derive_accept_key,
    make_websocket_key,
    parse_ws_url,
)

gc.collect()

from chumicro_websockets._session import InboundMessage, WhenOversized  # noqa: E402, I001 - preceded by gc.collect().

gc.collect()


def __getattr__(name):
    # Lazy PEP 562 import: the client/server half a board never references stays out of RAM.
    if name == "WebSocketClient":
        from chumicro_websockets.client import WebSocketClient  # noqa: PLC0415

        return WebSocketClient
    if name == "Connection":
        from chumicro_websockets.server import Connection  # noqa: PLC0415

        return Connection
    if name == "WebSocketServer":
        from chumicro_websockets.server import WebSocketServer  # noqa: PLC0415

        return WebSocketServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # pyright: ignore[reportUnsupportedDunderAll]: Connection,
    # WebSocketClient, and WebSocketServer are PEP-562 lazy via
    # __getattr__.
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
    "InboundMessage",
    "WebSocketBackpressureError",
    "WebSocketClient",
    "WebSocketError",
    "WebSocketHandshakeError",
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

gc.collect()
