"""Non-blocking HTTP/1.1 client for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  Tick-based runner contract — :meth:`HttpClient.check(now_ms)`
reports whether work is pending and :meth:`handle(now_ms)` does one
slice of progress per call, so an LED can keep blinking through a
request in flight, a TLS handshake, or a stalled-peer timeout.

Not supported: HTTP/1.1 keep-alive, gzip, cookies, streaming uploads,
multi-in-flight requests on the same client.
"""

import gc

from chumicro_requests._wire import (
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

gc.collect()


def __getattr__(name):
    """Lazy-load the client half on first access (PEP 562).

    ``client`` is ~25 KB of source.  A board that imports
    ``chumicro_requests`` for its wire helpers (URL parsing, header dict,
    request encoding) but never builds an ``HttpClient`` shouldn't pin
    the client's compiled code objects in RAM; the module loads on
    the first access to one of its symbols.  Constructing the
    client at startup keeps that one-time import cost on a fresh heap
    (see the guide).
    """
    if name in ("HttpClient", "RequestHandle", "Response", "WhenOversized"):
        # Pre-compile sweep; rationale in chumicro_mqtt.__getattr__.
        gc.collect()
        import chumicro_requests.client as _client  # noqa: PLC0415

        return getattr(_client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # pyright: ignore[reportUnsupportedDunderAll] — HttpClient,
    # RequestHandle, Response, and WhenOversized are PEP-562 lazy via
    # __getattr__.
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

gc.collect()
