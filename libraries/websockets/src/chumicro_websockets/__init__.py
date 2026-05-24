"""Non-blocking WebSocket client + server for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  Both :class:`WebSocketClient` and :class:`WebSocketServer`
follow the runner contract — :meth:`check(now_ms)` reports work
pending and :meth:`handle(now_ms)` does one slice of progress per
call, so an LED keeps blinking through the opening handshake, frame
I/O, control-frame interleave, and the close handshake.

End-of-module GC sweep follows the pattern documented in
:mod:`chumicro_mqtt`'s module docstring — the submodule chain here
(``_wire`` / ``_session`` / ``client`` / ``server``) wins the same
TLS-handshake headroom on Pi Pico W MP.
"""

import gc as _gc  # noqa: I001 — see chumicro_mqtt.__init__ docstring.

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
