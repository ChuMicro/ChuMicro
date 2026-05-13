"""Non-blocking HTTP/1.1 client for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  Tick-based runner contract — :meth:`HttpClient.check(now_ms)`
reports whether work is pending and :meth:`handle(now_ms)` does one
slice of progress per call, so an LED can keep blinking through a
request in flight, a TLS handshake, or a stalled-peer timeout.

Not supported: HTTP/1.1 keep-alive, gzip, cookies, streaming uploads,
multi-in-flight requests on the same client.
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
