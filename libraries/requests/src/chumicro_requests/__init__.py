"""``chumicro_requests`` sends HTTP and HTTPS requests on CircuitPython, MicroPython, and CPython,
one small step per pass of the main loop.

``HttpClient`` sends the requests.  ``client.get(url)`` returns a
``RequestHandle`` at once.  The main loop then calls ``client.check(now_ms)``
and ``client.handle(now_ms)``, which move the request forward until
``handle.done`` turns ``True``.  This package also holds the ``HttpError``
family, ``CaseInsensitiveDict``, and the wire helpers for code that frames
its own HTTP.  ``HttpClient``, ``RequestHandle``, ``Response``, and
``WhenOversized`` load from ``chumicro_requests.client`` on first use.
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
    # Lazy import keeps the ~25 KB client module out of RAM for boards
    # that use only the wire helpers.
    if name in ("HttpClient", "RequestHandle", "Response", "WhenOversized"):
        # Collect before the import so the client module compiles into a
        # swept heap rather than a fragmented one.
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
