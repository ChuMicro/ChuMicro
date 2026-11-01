"""``chumicro_http_server`` serves HTTP requests on CircuitPython, MicroPython, and CPython,
one small step per pass of the main loop.

``HttpServer`` runs the server.  ``@server.route(path)`` registers a handler,
and the main loop calls ``server.handle(now_ms)``.  This package also holds
the request parser, the error types, and the default size limits.
``HttpServer``, ``Request``, ``Response``, ``build_response``, and
``encode_response`` load from ``chumicro_http_server.server`` on first use.
"""

import gc

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


def __getattr__(name):
    # Lazy PEP 562 import: a wire-only board never loads the server module.
    if name in ("HttpServer", "Request", "Response", "build_response", "encode_response"):
        # Free the heap before the large import compiles.
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
