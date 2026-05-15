"""Non-blocking HTTP/1.1 server for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP listener + accepted client
sockets) and :mod:`chumicro_timing` (ticks).  Tick-based runner
contract — :meth:`HttpServer.check(now_ms)` reports whether work is
pending and :meth:`handle(now_ms)` does one slice of progress per
call, so an LED can keep blinking on the same board even through a
slow upload or stalled client.

Not supported: HTTP/1.1 keep-alive or connection pooling (every
response carries ``Connection: close``); chunked request bodies
(use ``Content-Length``); WebSockets, sessions / cookies / auth
helpers, multipart upload, sub-app mounting, async handlers.
"""

from chumicro_http_server._wire import (
    DEFAULT_BODY_BUFFER_SIZE,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_REQUEST_BODY_BYTES,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_REQUEST_TIMEOUT_MS,
    DEFAULT_SEND_BUDGET_PER_TICK,
    CaseInsensitiveDict,
    RequestParser,
    RequestParseState,
    ServerError,
    ServerOversizedError,
    ServerProtocolError,
    parse_charset,
    parse_query,
    split_target,
)
from chumicro_http_server.server import (
    HttpServer,
    Request,
    Response,
    build_response,
    encode_response,
)

__all__ = [
    "DEFAULT_BODY_BUFFER_SIZE",
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_MAX_REQUEST_BODY_BYTES",
    "DEFAULT_RECV_BUDGET_PER_TICK",
    "DEFAULT_REQUEST_TIMEOUT_MS",
    "DEFAULT_SEND_BUDGET_PER_TICK",
    "CaseInsensitiveDict",
    "HttpServer",
    "Request",
    "RequestParseState",
    "RequestParser",
    "Response",
    "ServerError",
    "ServerOversizedError",
    "ServerProtocolError",
    "build_response",
    "encode_response",
    "parse_charset",
    "parse_query",
    "split_target",
]
