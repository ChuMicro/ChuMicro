"""Non-blocking HTTP/1.1 client for CircuitPython, MicroPython, and CPython."""

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
