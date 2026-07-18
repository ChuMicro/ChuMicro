"""Non-blocking HTTP/1.1 server for CircuitPython, MicroPython, and CPython.

Tick-based: :meth:`HttpServer.check` reports whether work is pending and
:meth:`HttpServer.handle` does one slice of progress per call, so the
caller's loop keeps running other work through a slow or stalled client.
Keep-alive, chunked request bodies, WebSockets, cookies, and multipart
upload are not supported.
"""

import gc

# Streamed bodies live in the opt-in ``streaming`` submodule (not
# re-exported here), so a server that never streams never loads that code.
from chumicro_http_server._wire import (
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_HEADERS_BYTES,
    DEFAULT_MAX_REQUEST_BODY_BYTES,
    DEFAULT_MAX_REQUEST_LINE_BYTES,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_REQUEST_TIMEOUT_MS,
    DEFAULT_SEND_BUDGET_PER_TICK,
    DEFAULT_STREAM_BUFFER_SIZE,
    SOURCE_EOF,
    CaseInsensitiveDict,
    RequestParser,
    RequestParseState,
    ServerError,
    ServerHeadersTooLargeError,
    ServerLimitError,
    ServerOversizedError,
    ServerProtocolError,
    ServerRequestLineTooLargeError,
    parse_charset,
    parse_query,
    split_target,
)

gc.collect()


def __getattr__(name):
    # Lazy PEP 562 import: a board that only uses the wire helpers never
    # pins the server module's ~22 KB of compiled code in RAM.
    if name in ("HttpServer", "Request", "Response", "build_response", "encode_response"):
        # Sweep before the big compile (see chumicro_mqtt.__getattr__).
        gc.collect()
        import chumicro_http_server.server as _server  # noqa: PLC0415

        return getattr(_server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # pyright: ignore[reportUnsupportedDunderAll]: HttpServer, Request,
    # Response, build_response, and encode_response are PEP-562 lazy via
    # __getattr__.
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_MAX_HEADERS_BYTES",
    "DEFAULT_MAX_REQUEST_BODY_BYTES",
    "DEFAULT_MAX_REQUEST_LINE_BYTES",
    "DEFAULT_RECV_BUDGET_PER_TICK",
    "DEFAULT_REQUEST_TIMEOUT_MS",
    "DEFAULT_SEND_BUDGET_PER_TICK",
    "DEFAULT_STREAM_BUFFER_SIZE",
    "SOURCE_EOF",
    "CaseInsensitiveDict",
    "HttpServer",
    "Request",
    "RequestParseState",
    "RequestParser",
    "Response",
    "ServerError",
    "ServerHeadersTooLargeError",
    "ServerLimitError",
    "ServerOversizedError",
    "ServerProtocolError",
    "ServerRequestLineTooLargeError",
    "build_response",
    "encode_response",
    "parse_charset",
    "parse_query",
    "split_target",
]

gc.collect()
