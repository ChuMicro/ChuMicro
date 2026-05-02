"""Non-blocking HTTP/1.1 server for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP listener + accepted client
sockets) and :mod:`chumicro_timing` (ticks) only — the shared
HTTP/1.1 wire primitives (case-insensitive header dict, charset
parsing) are inlined into :mod:`chumicro_http_server._wire` so a
server-only board doesn't need to ship the full client library.
No async, no threads — Decision 0014's runner pattern:
:meth:`HttpServer.check(now_ms) -> bool` reports whether work is
pending; :meth:`handle(now_ms)` does one tick of progress.  The
canonical promise (Decision 0041): an LED can keep blinking on the
same board while requests are being served, even through a slow
upload or a stalled client.

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

Source layout (mirrors chumicro-requests' post-Decision-0029 split):

* :mod:`chumicro_http_server._wire` — `RequestParser` streaming
  state machine, request-target helpers, exception classes,
  protocol constants.
* :mod:`chumicro_http_server.server` — `HttpServer`, `Request`,
  `Response`, per-connection state machine, response writer,
  `build_response()` helper.

v1 (Decision 0041) shipped across slices 7a–7d: listener + request
line + header parser + canned response (7a), `@server.route`
decorator + JSON helpers + multi-method dispatch (7b), bounded
multi-connection + per-tick budgets + request_timeout_ms (7c),
and live-board verification on Pi Pico W (7d).

TLS-server support is provided transport-side by
:func:`chumicro_sockets.ssl_context_with_cert_and_key_paths` —
wrap the listener your ``listener_factory`` returns.  Verified
working on every supported runtime/board pair *except* CP-on-rp2,
where ``chumicro_sockets.tls_listening_socket`` refuses up-front
with ``UnsupportedSSLConfigError`` (use ESP32-family or
MicroPython on the same Pi Pico W for HTTPS).

v1 non-goals: WebSockets, sessions / cookies / auth helpers,
multipart upload, sub-app mounting, async handlers.  See
Decision 0041 §8.
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
