"""Non-blocking WebSocket client + server for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  Both :class:`WebSocketClient` and :class:`WebSocketServer`
follow the runner contract — :meth:`check(now_ms)` reports work
pending and :meth:`handle(now_ms)` does one slice of progress per
call, so an LED keeps blinking through the opening handshake, frame
I/O, control-frame interleave, and the close handshake.
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
    """Lazy-load the client / server halves on first access (PEP 562).

    ``client`` and ``server`` are ~20 KB of source each.  A client-only
    app — the common Pico W case — never touches ``WebSocketServer`` /
    ``Connection``, and a server-only app never touches
    ``WebSocketClient``, so importing both eagerly would pin the unused
    half's compiled code objects in RAM.  Deferring each until its first
    attribute access keeps only the half a deployment uses resident.
    """
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
    # pyright: ignore[reportUnsupportedDunderAll] — Connection,
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
