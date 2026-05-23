"""Non-blocking WebSocket client + server for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  Both :class:`WebSocketClient` and :class:`WebSocketServer`
follow the runner contract — :meth:`check(now_ms)` reports work
pending and :meth:`handle(now_ms)` does one slice of progress per
call, so an LED keeps blinking through the opening handshake, frame
I/O, control-frame interleave, and the close handshake.

This module sweeps the GC between and after its submodule imports.
On MicroPython, compile-time scratch (AST nodes, transient tuples,
interned-name artifacts) from loading ``_wire.py`` / ``_session.py``
/ ``client.py`` / ``server.py`` stays resident until auto-GC fires
under allocation pressure — which a successful import never triggers,
leaving the scratch interleaved with the persistent module state.
The explicit collects defragment that pattern, restoring TLS
handshake headroom on Pi Pico W MP that the chain otherwise loses.
On CPython the calls are benign.
"""

import gc as _gc  # noqa: I001 — gc.collect() interleaved with imports is intentional; see module docstring.

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
_gc.collect()

from chumicro_websockets.client import WebSocketClient, WhenOversized  # noqa: E402, I001 — gc.collect() interleaved with imports is intentional.
_gc.collect()

from chumicro_websockets.server import Connection, WebSocketServer  # noqa: E402, I001 — gc.collect() interleaved with imports is intentional.

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

_gc.collect()
del _gc
