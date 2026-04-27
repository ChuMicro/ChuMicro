"""Non-blocking HTTP/1.1 client for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  No async, no threads — Decision 0014's runner pattern:
:meth:`HttpClient.check(now_ms) -> bool` reports whether work is
pending; :meth:`handle(now_ms)` does one tick of progress.  The
canonical promise (Decision 0040): an LED can keep blinking on the
same board while a request is in flight, in a TLS handshake, or
mid-timeout against a stalled peer.

Public API::

    from chumicro_requests import HttpClient, chumicro_sockets_factory
    from chumicro_timing import ticks_ms

    client = HttpClient(connection_factory=chumicro_sockets_factory(radio=wifi.radio))
    handle = client.get("http://api.example.com/now", timeout_ms=5000)

    while not handle.done:
        if client.check(ticks_ms()):
            client.handle(ticks_ms())

    response = handle.result    # raises HttpError on failure
    print(response.status_code, response.headers["content-type"], response.body)

Source layout (mirrors :mod:`chumicro_mqtt`'s post-Decision-0029 split):

* :mod:`chumicro_requests._wire` — URL parser, request encoder,
  streaming response parser, case-insensitive header dict, exception
  hierarchy, protocol constants.
* :mod:`chumicro_requests.client` — :class:`HttpClient`,
  :class:`RequestHandle`, :class:`Response`, :class:`WhenOversized`
  policy enum, :func:`chumicro_sockets_factory` convenience helper.

v1 scope (Decision 0040): plain HTTP GET (slice 3a), body decode
(slice 3b), HTTPS via :mod:`chumicro_sockets` TLS (slice 3c), POST +
JSON helpers (slice 3d), redirects (slice 3e), chunked transfer
encoding (slice 3f).  No keep-alive, no gzip, no cookies — see
Decision 0040 §7 for the full v1 non-goal list.
"""

from chumicro_requests._wire import (
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_TIMEOUT_MS,
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
)
from chumicro_requests.client import (
    HttpClient,
    RequestHandle,
    Response,
    WhenOversized,
    chumicro_sockets_factory,
)

__all__ = [
    "DEFAULT_MAX_BODY_BYTES",
    "DEFAULT_RECV_BUDGET_PER_TICK",
    "DEFAULT_TIMEOUT_MS",
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
    "chumicro_sockets_factory",
    "encode_request",
    "parse_charset",
    "parse_url",
]
