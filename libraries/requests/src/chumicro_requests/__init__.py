"""Non-blocking HTTP/1.1 client for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  No async, no threads — a tick-based runner contract:
:meth:`HttpClient.check(now_ms) -> bool` reports whether work is
pending; :meth:`handle(now_ms)` does one tick of progress, so an
LED can keep blinking on the same board while a request is in
flight, in a TLS handshake, or mid-timeout against a stalled peer.

Public API::

    from chumicro_requests import HttpClient
    from chumicro_requests.sockets_factory import chumicro_sockets_factory
    from chumicro_timing import ticks_ms

    client = HttpClient(connection_factory=chumicro_sockets_factory())
    handle = client.get("http://api.example.com/now", timeout_ms=5000)

    while not handle.done:
        now = ticks_ms()
        if client.check(now):
            client.handle(now)

    response = handle.result    # raises HttpError on failure
    print(response.status_code, response.headers["content-type"], response.body)

Source layout:

* :mod:`chumicro_requests._wire` — URL parser, request encoder,
  streaming response parser, case-insensitive header dict, exception
  hierarchy, protocol constants.
* :mod:`chumicro_requests.client` — :class:`HttpClient`,
  :class:`RequestHandle`, :class:`Response`, :class:`WhenOversized`
  policy enum.
* :mod:`chumicro_requests.sockets_factory` — opt-in
  :func:`chumicro_sockets_factory` convenience helper that wires
  the default :mod:`chumicro_sockets` transport.  Lives in its own
  submodule so users with a custom ``connection_factory`` never
  trigger the :mod:`chumicro_sockets` deploy.

v1 scope: plain HTTP GET, body decode, HTTPS via
:mod:`chumicro_sockets` TLS, POST + JSON helpers, redirects, chunked
transfer encoding.  v1 non-goals: keep-alive, gzip, cookies,
streaming uploads, multi-in-flight requests.
"""

from chumicro_requests._wire import (
    DEFAULT_RECV_BUDGET_PER_TICK,
    CaseInsensitiveDict,
    HttpBusyError,
    HttpError,
    HttpOversizedError,
    HttpProtocolError,
    HttpTimeoutError,
    HttpURLError,
    ParseState,
    ResponseParser,
    encode_request,
    parse_charset,
    parse_url,
    resolve_redirect_url,
)
from chumicro_requests.client import (
    HttpClient,
    RequestHandle,
    Response,
    WhenOversized,
)

__all__ = [
    "DEFAULT_RECV_BUDGET_PER_TICK",
    "CaseInsensitiveDict",
    "HttpBusyError",
    "HttpClient",
    "HttpError",
    "HttpOversizedError",
    "HttpProtocolError",
    "HttpTimeoutError",
    "HttpURLError",
    "ParseState",
    "RequestHandle",
    "Response",
    "ResponseParser",
    "WhenOversized",
    "encode_request",
    "parse_charset",
    "parse_url",
    "resolve_redirect_url",
]
