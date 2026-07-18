"""Non-blocking HTTP/1.1 client for CircuitPython, MicroPython, and CPython.

The client is tick-based: :meth:`HttpClient.check` reports whether work
is pending and :meth:`handle` makes one slice of progress per call, so
other tasks keep running while a request is in flight. v1 does not do
keep-alive, gzip, cookies, streaming uploads, or several in-flight
requests on one client.
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
    # Lazy PEP 562 import: a board that uses only the wire helpers (URL
    # parsing, header dict, request encoding) never pins the ~25 KB
    # client module in RAM.
    if name in ("HttpClient", "RequestHandle", "Response", "WhenOversized"):
        # Pre-compile sweep; rationale in chumicro_mqtt.__getattr__.
        gc.collect()
        import chumicro_requests.client as _client  # noqa: PLC0415

        return getattr(_client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # pyright: ignore[reportUnsupportedDunderAll]: HttpClient,
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
