"""Non-blocking HTTP/1.1 server for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP listener + accepted client
sockets), :mod:`chumicro_timing` (ticks), and :mod:`chumicro_requests`
(shared wire-format primitives — `CaseInsensitiveDict`,
`parse_charset`, exception hierarchy).  No async, no threads —
Decision 0014's runner pattern: :meth:`HttpServer.check(now_ms) -> bool`
reports whether work is pending; :meth:`handle(now_ms)` does one tick
of progress.  The canonical promise (Decision 0041): an LED can keep
blinking on the same board while requests are being served, even
through a slow upload or a stalled client.

Public API::

    from chumicro_http_server import HttpServer, build_response
    from chumicro_sockets import tcp_listening_socket
    from chumicro_timing import ticks_ms

    def handle_request(request):
        if request.method == "GET" and request.path == "/":
            return build_response(200, text="hello, world!")
        return build_response(404, text="not found")

    server = HttpServer(
        listener_factory=lambda: tcp_listening_socket(
            host="0.0.0.0", port=8080, radio=wifi.radio,
        ),
        handler=handle_request,
    )

    while True:
        if server.check(ticks_ms()):
            server.handle(ticks_ms())

Source layout (mirrors :mod:`chumicro_requests`'s post-Decision-0029 split):

* :mod:`chumicro_http_server._wire` — `RequestParser` streaming
  state machine, request-target helpers, exception classes,
  protocol constants.
* :mod:`chumicro_http_server.server` — `HttpServer`, `Request`,
  `Response`, per-connection state machine, response writer,
  `build_response()` helper.

v1 scope (Decision 0041): slice 7a — listener + request line +
header parser + canned response.  Slices 7b (routing decorator
+ JSON helpers + multi-method dispatch), 7c (bounded multi-
connection + per-tick budgets + request_timeout_ms), 7d (live-board
verification on Pi Pico W) round out v1.

v1 non-goals: TLS server (Pi Pico W can't host the handshake),
WebSockets, sessions / cookies / auth helpers, multipart upload,
sub-app mounting, async handlers.  See Decision 0041 §8.
"""

from chumicro_http_server._wire import (
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_REQUEST_BODY_BYTES,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_REQUEST_TIMEOUT_MS,
    DEFAULT_SEND_BUDGET_PER_TICK,
    CaseInsensitiveDict,
    RequestParser,
    RequestParseState,
    ServerError,
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
    "ServerProtocolError",
    "build_response",
    "encode_response",
    "parse_charset",
    "parse_query",
    "split_target",
]
