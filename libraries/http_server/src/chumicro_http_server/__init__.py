"""Non-blocking HTTP/1.1 server for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP listener + accepted client
sockets) and :mod:`chumicro_timing` (ticks) only — the shared
HTTP/1.1 wire primitives (case-insensitive header dict, charset
parsing) are inlined into :mod:`chumicro_http_server._wire` so a
server-only board doesn't need to ship the full client library.
No async, no threads — a tick-based runner contract:
:meth:`HttpServer.check(now_ms) -> bool` reports whether work is
pending; :meth:`handle(now_ms)` does one tick of progress, so an
LED can keep blinking on the same board while requests are being
served, even through a slow upload or a stalled client.

Public API::

    import wifi

    from chumicro_http_server import HttpServer, build_response
    from chumicro_http_server.sockets_factory import chumicro_sockets_factory
    from chumicro_timing import ticks_ms

    def handle_request(request):
        if request.method == "GET" and request.path == "/":
            return build_response(200, text="hello, world!")
        return build_response(404, text="not found")

    server = HttpServer(
        listener_factory=chumicro_sockets_factory(
            {"http_server.bind_port": 8080}, radio=wifi.radio,
        ),
        handler=handle_request,
    )

    while True:
        now = ticks_ms()
        if server.check(now):
            server.handle(now)

Source layout:

* :mod:`chumicro_http_server._wire` — `RequestParser` streaming
  state machine, request-target helpers, exception classes,
  protocol constants.
* :mod:`chumicro_http_server.server` — `HttpServer`, `Request`,
  `Response`, per-connection state machine, response writer,
  `build_response()` helper.
* :mod:`chumicro_http_server.sockets_factory` — opt-in
  :func:`chumicro_sockets_factory` convenience helper that wires
  the default :mod:`chumicro_sockets` listener (plain TCP or TLS,
  driven by config).  Lives in its own submodule so users with a
  custom ``listener_factory`` never trigger the
  :mod:`chumicro_sockets` deploy.

TLS-server support is provided transport-side by
:func:`chumicro_sockets.ssl_context_with_cert_and_key_paths` —
wrap the listener your ``listener_factory`` returns.  Verified
working on every supported runtime/board pair *except* CP-on-rp2,
where ``chumicro_sockets.tls_listening_socket`` refuses up-front
with ``UnsupportedSSLConfigError`` (use ESP32-family or
MicroPython on the same Pi Pico W for HTTPS).

Not supported: HTTP/1.1 keep-alive or connection pooling (each
request is served on a fresh accepted socket and ``Connection: close``
is added to every response); chunked request bodies (use
``Content-Length`` instead); WebSockets, sessions / cookies / auth
helpers, multipart upload, sub-app mounting, async handlers.
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
