"""HTTP/1.1 wire format for chumicro-requests.

Consolidates URL parsing, request encoding, response parsing, the
case-insensitive header dict, exception hierarchy, and protocol
constants.  Keeping wire-format primitives in one module mirrors
the post-Decision-0029 :mod:`chumicro_mqtt._wire` shape — one file
of bytes-on-the-wire, one file of orchestration.

The response parser is a streaming state machine fed raw bytes via
:meth:`ResponseParser.feed`; it transitions
``STATUS -> HEADERS -> BODY -> DONE`` as bytes arrive.  No socket I/O
here — the client drives the socket and feeds bytes in.

v1 scope (Decision 0040):

* Plain HTTP only — ``https://`` URLs parse, but the client refuses
  to dial them until slice 3c lands.
* Body is buffered in full (capped by ``max_body_bytes``).
* ``Content-Length``-framed responses + read-until-close.  Chunked
  transfer-encoding decode lands in slice 3f.
* No header folding (RFC 7230 deprecates it); multi-value headers
  join with ``, `` per RFC 7230 §3.2.2.
"""

try:
    from micropython import const
except ImportError:
    def const(value):
        return value


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class HttpError(Exception):
    """Base class for every chumicro-requests failure."""


class HttpProtocolError(HttpError):
    """Server sent bytes the spec doesn't allow.

    Malformed status line, header without a colon, body shorter than
    the advertised ``Content-Length``, etc.  Always a peer or network
    bug — the right response is usually fail the request and surface
    the error to the caller.
    """


class HttpTimeoutError(HttpError):
    """Per-request ``timeout_ms`` budget elapsed before the response completed."""


class HttpBusyError(HttpError):
    """Caller issued a request while another was still in flight.

    Mirrors :class:`chumicro_mqtt.MQTTBackpressureError`.  v1 of
    chumicro-requests is single-in-flight (Decision 0040 §1) — the
    caller must wait for ``handle.done`` before issuing another.
    """


class HttpURLError(HttpError):
    """URL doesn't parse as a supported HTTP/HTTPS URL."""


class HttpOversizedError(HttpError):
    """Response body exceeded ``max_body_bytes``.

    Raised when ``when_oversized=DISCONNECT`` (Decision 0040 §3).
    The other policies (``DROP_SILENT``, ``DROP_WITH_EVENT``) drop
    the payload silently or fire an event without raising.
    """


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default max buffered response body — Decision 0040 §3.  64 KB
#: leaves headroom on a Decision 0015 minimum board (256 KB MCU RAM).
DEFAULT_MAX_BODY_BYTES = const(65536)

#: Default per-tick recv cap — Decision 0040 §3.  Mirrors
#: :data:`chumicro_mqtt.MQTTClient` default; keeps tick latency
#: LED-friendly.
DEFAULT_RECV_BUDGET_PER_TICK = const(1024)

#: Default per-request timeout in ms — Decision 0040 §3.
DEFAULT_TIMEOUT_MS = const(10000)

#: HTTP/1.1 line terminator.
CRLF = b"\r\n"

#: Header / body separator.
CRLF_CRLF = b"\r\n\r\n"

#: Status codes that MUST NOT have a body per RFC 7230 §3.3.3.  We
#: short-circuit body parsing for these to avoid hanging on a server
#: that omits ``Content-Length: 0``.
NO_BODY_STATUS_CODES = frozenset({204, 304})


# ---------------------------------------------------------------------------
# Content-Type charset parsing
# ---------------------------------------------------------------------------


def parse_charset(content_type: str | None) -> str:
    """Extract the ``charset=...`` parameter from a Content-Type header.

    Per RFC 7231 §3.1.1.5 the Content-Type value may carry a
    ``charset`` parameter — for example ``text/html; charset=utf-8``
    or ``application/json; charset="ISO-8859-1"``.  We tokenize on
    semicolons, look for a ``charset=`` token (case-insensitive),
    strip optional surrounding quotes per RFC 7231 §3.1.1.1, and
    fall back to ``"utf-8"`` when no charset is present or the
    header itself is missing.

    Defaulting to UTF-8 matches RFC 8259 §8.1 for ``application/json``
    and aligns with current web practice for ``text/*`` even though
    historical RFC 2616 defaulted text to ISO-8859-1.

    Args:
        content_type: Raw ``Content-Type`` header value, or ``None``.

    Returns:
        The detected charset name, or ``"utf-8"`` as the safe default.
    """
    if not content_type:
        return "utf-8"
    parts = content_type.split(";")
    for part in parts[1:]:
        token = part.strip()
        if token[:8].lower() != "charset=":
            continue
        value = token[8:].strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        return value or "utf-8"
    return "utf-8"


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------


def parse_url(url: str) -> tuple[str, str, int, str]:
    """Split *url* into ``(scheme, host, port, path)``.

    Args:
        url: HTTP or HTTPS URL.  Examples:
            ``http://example.com/`` → ``("http", "example.com", 80, "/")``
            ``http://example.com:8080/path?q=1`` →
            ``("http", "example.com", 8080, "/path?q=1")``
            ``https://example.com`` → ``("https", "example.com", 443, "/")``

    Returns:
        4-tuple ``(scheme, host, port, path)``.  *path* always starts
        with ``/`` and includes the query string if present.

    Raises:
        HttpURLError: Scheme is not ``http`` / ``https``, host is
            missing, or port is not a base-10 integer.
    """
    if not isinstance(url, str):
        raise HttpURLError(f"url must be str, got {type(url).__name__}")
    if url.startswith("http://"):
        scheme = "http"
        rest = url[7:]
        default_port = 80
    elif url.startswith("https://"):
        scheme = "https"
        rest = url[8:]
        default_port = 443
    else:
        raise HttpURLError(
            f"url must start with http:// or https://, got {url!r}",
        )
    if not rest:
        raise HttpURLError(f"url is missing host: {url!r}")

    slash_index = rest.find("/")
    if slash_index == -1:
        host_and_port = rest
        path = "/"
    else:
        host_and_port = rest[:slash_index]
        path = rest[slash_index:]

    if not host_and_port:
        raise HttpURLError(f"url is missing host: {url!r}")

    colon_index = host_and_port.find(":")
    if colon_index == -1:
        host = host_and_port
        port = default_port
    else:
        host = host_and_port[:colon_index]
        port_str = host_and_port[colon_index + 1:]
        if not host:
            raise HttpURLError(f"url is missing host: {url!r}")
        try:
            port = int(port_str)
        except ValueError as parse_error:
            raise HttpURLError(
                f"url has non-integer port {port_str!r}: {url!r}",
            ) from parse_error
        if port <= 0 or port > 65535:
            raise HttpURLError(
                f"url port {port} out of range 1-65535: {url!r}",
            )
    return scheme, host, port, path


# ---------------------------------------------------------------------------
# Case-insensitive header dict
# ---------------------------------------------------------------------------


class CaseInsensitiveDict:
    """Header dict whose lookups fold to lowercase.

    HTTP/1.1 §3.2 requires header names to be case-insensitive on
    receipt (servers and clients alike).  We store the original-cased
    name (so callers see ``Content-Type`` and not ``content-type``)
    keyed off the lowercased form.

    Multi-value headers (``Set-Cookie``, ``Via``) join with ``, ``
    per RFC 7230 §3.2.2 when the same header arrives twice; v1 has
    no cookie jar so the join is informational.

    Implements ``__getitem__`` / ``__setitem__`` / ``__contains__`` /
    ``__len__`` / ``__iter__`` / ``get`` / ``items`` — enough for the
    response API surface.  Not a full :class:`MutableMapping` to keep
    the embedded footprint small.
    """

    def __init__(self):
        # Lowercase key -> (original_name, value).
        self._entries = {}

    def __setitem__(self, name, value):
        lower = name.lower()
        self._entries[lower] = (name, value)

    def __getitem__(self, name):
        return self._entries[name.lower()][1]

    def __contains__(self, name):
        return name.lower() in self._entries

    def __iter__(self):
        for original_name, _value in self._entries.values():
            yield original_name

    def __len__(self):
        return len(self._entries)

    def __eq__(self, other):
        if not isinstance(other, CaseInsensitiveDict):
            return NotImplemented
        if len(self._entries) != len(other._entries):
            return False
        for lower, (_name, value) in self._entries.items():
            if lower not in other._entries:
                return False
            if other._entries[lower][1] != value:
                return False
        return True

    def __repr__(self):
        pairs = ", ".join(
            f"{name!r}: {value!r}"
            for name, value in self.items()
        )
        return f"CaseInsensitiveDict({{{pairs}}})"

    def get(self, name, default=None):
        """Return the value for *name* or *default* if missing."""
        entry = self._entries.get(name.lower())
        if entry is None:
            return default
        return entry[1]

    def items(self):
        """Yield ``(original_name, value)`` pairs."""
        yield from self._entries.values()

    def add(self, name, value):
        """Append *value* to the existing header, joining with ``, ``.

        New keys behave like :meth:`__setitem__`.  Used by the parser
        for repeated header lines (``Set-Cookie``, ``Via``).
        """
        lower = name.lower()
        existing = self._entries.get(lower)
        if existing is None:
            self._entries[lower] = (name, value)
            return
        original_name, current_value = existing
        joined = f"{current_value}, {value}"
        self._entries[lower] = (original_name, joined)


# ---------------------------------------------------------------------------
# Request encoding
# ---------------------------------------------------------------------------


def encode_request(
    method: str,
    host: str,
    path: str,
    *,
    headers: object | None = None,
    body: bytes | None = None,
    user_agent: str | None = None,
) -> bytes:
    """Encode an HTTP/1.1 request into bytes ready for the wire.

    Args:
        method: HTTP verb — ``"GET"``, ``"POST"``, etc.  Sent verbatim.
        host: Value for the ``Host:`` header (typically the URL host;
            include the port via ``"host:port"`` if non-default).
        path: Request-target — typically the URL path + query.
        headers: Optional iterable of ``(name, value)`` pairs, a plain
            ``dict``, or a :class:`CaseInsensitiveDict`.  Caller-supplied
            headers override the defaults (``Host``, ``User-Agent``,
            ``Accept``, ``Accept-Encoding``, ``Connection``).
        body: Optional ``bytes`` body.  When set, ``Content-Length`` is
            auto-added (callers can override via *headers*).
        user_agent: Override the default ``User-Agent`` string.

    Returns:
        Encoded request as ``bytes``.
    """
    merged = CaseInsensitiveDict()
    merged["Host"] = host
    merged["User-Agent"] = user_agent or "chumicro-requests/0.1"
    merged["Accept"] = "*/*"
    # Decision 0040 §7 — no gzip in v1; require identity from peers.
    merged["Accept-Encoding"] = "identity"
    # No keep-alive in v1 — one socket per request.  The peer will
    # close after the response; our parser uses that as the
    # end-of-body sentinel when no Content-Length is present.
    merged["Connection"] = "close"
    if body is not None:
        merged["Content-Length"] = str(len(body))

    if headers is not None:
        if isinstance(headers, CaseInsensitiveDict):
            iterable = headers.items()
        elif isinstance(headers, dict):
            iterable = headers.items()
        else:
            iterable = headers
        for name, value in iterable:
            merged[name] = value

    parts = [f"{method} {path} HTTP/1.1\r\n".encode("ascii")]
    for name, value in merged.items():
        parts.append(f"{name}: {value}\r\n".encode("ascii"))
    parts.append(CRLF)
    if body is not None:
        parts.append(body)
    return b"".join(parts)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


class ParseState:
    """Streaming response parser states.

    Forward-only::

      STATUS -> HEADERS -> BODY -> DONE
                              \\-> ERROR
    """

    STATUS = "status"
    HEADERS = "headers"
    BODY = "body"
    DONE = "done"
    ERROR = "error"


class ResponseParser:
    """Streaming HTTP/1.1 response parser.

    Fed raw bytes via :meth:`feed`; the state advances as soon as
    enough bytes have arrived.  Callers check :attr:`state` to know
    whether to keep feeding (anything other than ``DONE``/``ERROR``)
    or stop (``DONE``).

    Body framing supported in slice 3a:

    * ``Content-Length: N`` — read exactly N bytes.
    * No ``Content-Length`` — read until the peer closes (signaled by
      :meth:`feed_eof`).

    Chunked transfer-encoding lands in slice 3f.

    The ``max_body_bytes`` cap is enforced incrementally — once total
    body bytes pass the cap the parser raises (or drops, depending on
    *when_oversized*) on the first :meth:`feed` past the threshold.
    """

    def __init__(self, *, max_body_bytes=DEFAULT_MAX_BODY_BYTES):
        self._max_body_bytes = max_body_bytes
        self._buffer = bytearray()
        self._state = ParseState.STATUS
        self._status_code = None
        self._reason = ""
        self._http_version = ""
        self._headers = CaseInsensitiveDict()
        self._body = bytearray()
        # -1 = unknown (read until close).  Set to a non-negative
        # value when Content-Length parses successfully.
        self._body_remaining = -1
        self._error = None

    # ------------------------------------------------------------------
    # Public observation
    # ------------------------------------------------------------------

    @property
    def state(self):
        """Current :class:`ParseState`."""
        return self._state

    @property
    def status_code(self):
        """HTTP status code (e.g. 200) once headers parse, else ``None``."""
        return self._status_code

    @property
    def reason(self):
        """Reason phrase (e.g. ``"OK"``) once headers parse, else ``""``."""
        return self._reason

    @property
    def http_version(self):
        """HTTP version string (e.g. ``"HTTP/1.1"``) once status line parses."""
        return self._http_version

    @property
    def headers(self):
        """Case-insensitive :class:`CaseInsensitiveDict` of response headers."""
        return self._headers

    @property
    def body(self):
        """Body bytes received so far (final once :attr:`state` is ``DONE``)."""
        return bytes(self._body)

    @property
    def error(self):
        """Last error raised during parsing or ``None``."""
        return self._error

    # ------------------------------------------------------------------
    # Driving the parser
    # ------------------------------------------------------------------

    def feed(self, chunk):
        """Append *chunk* to the parser's buffer and advance the state.

        Raises :class:`HttpProtocolError` (or :class:`HttpOversizedError`)
        when the bytes can't be reconciled with HTTP/1.1.
        """
        if self._state in (ParseState.DONE, ParseState.ERROR):
            return
        if chunk:
            if self._state == ParseState.BODY:
                # Skip the staging buffer for body bytes — straight in.
                self._absorb_body_bytes(chunk)
            else:
                self._buffer.extend(chunk)
        self._advance()

    def feed_eof(self):
        """Signal that the peer closed the connection.

        For a ``Content-Length``-framed response this is a protocol
        error if the body was short.  For a length-unknown response
        (no ``Content-Length``, no ``Transfer-Encoding``) this is the
        normal end-of-body signal.
        """
        if self._state == ParseState.DONE:
            return
        if self._state == ParseState.ERROR:
            return
        if self._state == ParseState.BODY and self._body_remaining < 0:
            # Length-unknown body; peer-close == done.
            self._state = ParseState.DONE
            return
        if self._state == ParseState.BODY and self._body_remaining > 0:
            self._fail(HttpProtocolError(
                f"peer closed mid-body; {self._body_remaining} bytes "
                "still expected per Content-Length",
            ))
            return
        # Mid-headers or mid-status — peer hung up before responding.
        self._fail(HttpProtocolError(
            f"peer closed before response completed (state={self._state})",
        ))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _advance(self):
        """Consume buffered bytes until no more progress is possible."""
        while True:
            if self._state == ParseState.STATUS:
                if not self._try_parse_status_line():
                    return
                continue
            if self._state == ParseState.HEADERS:
                progressed = self._try_parse_headers()
                if not progressed:
                    return
                continue
            return  # BODY (handled in feed) / DONE / ERROR

    def _try_parse_status_line(self):
        """Consume one status line; return True if state advanced."""
        crlf_index = self._buffer.find(CRLF)
        if crlf_index == -1:
            return False
        line = bytes(self._buffer[:crlf_index])
        # CircuitPython 10.x's bytearray rejects ``del buffer[:n]``
        # (TypeError: "'bytearray' object doesn't support item
        # deletion") even though MicroPython and CPython both accept
        # it.  Reassign via slice for cross-runtime safety.  The buffer
        # stays tiny (status line < ~50 B, headers < ~1 KB), so the
        # extra copy is negligible.
        self._buffer = bytearray(self._buffer[crlf_index + 2:])
        # Status-Line per RFC 7230 §3.1.2: HTTP-version SP status-code SP reason-phrase
        try:
            text = line.decode("ascii")
        except UnicodeDecodeError as decode_error:
            self._fail(HttpProtocolError(
                f"non-ASCII status line: {line!r}",
            ))
            raise self._error from decode_error
        parts = text.split(" ", 2)
        if len(parts) < 2:
            self._fail(HttpProtocolError(f"malformed status line: {text!r}"))
            return True
        version_str, code_str = parts[0], parts[1]
        if not version_str.startswith("HTTP/"):
            self._fail(HttpProtocolError(
                f"status line missing HTTP version: {text!r}",
            ))
            return True
        try:
            self._status_code = int(code_str)
        except ValueError:
            self._fail(HttpProtocolError(
                f"non-integer status code: {code_str!r}",
            ))
            return True
        self._http_version = version_str
        self._reason = parts[2] if len(parts) == 3 else ""
        self._state = ParseState.HEADERS
        return True

    def _try_parse_headers(self):
        """Consume one header line; return True if state advanced or
        another header was parsed."""
        crlf_index = self._buffer.find(CRLF)
        if crlf_index == -1:
            return False
        if crlf_index == 0:
            # Empty line — end of headers.  Reassign via slice for
            # CircuitPython compatibility (see _try_parse_status_line).
            self._buffer = bytearray(self._buffer[2:])
            self._enter_body_state()
            return True
        line = bytes(self._buffer[:crlf_index])
        self._buffer = bytearray(self._buffer[crlf_index + 2:])
        try:
            text = line.decode("ascii")
        except UnicodeDecodeError as decode_error:
            self._fail(HttpProtocolError(
                f"non-ASCII header line: {line!r}",
            ))
            raise self._error from decode_error
        colon_index = text.find(":")
        if colon_index <= 0:
            self._fail(HttpProtocolError(
                f"header line missing ':' or empty name: {text!r}",
            ))
            return True
        name = text[:colon_index]
        value = text[colon_index + 1:].strip()
        self._headers.add(name, value)
        return True

    def _enter_body_state(self):
        """Headers-complete: figure out body framing."""
        if self._status_code in NO_BODY_STATUS_CODES or (
            100 <= self._status_code < 200
        ):
            self._state = ParseState.DONE
            return
        content_length_str = self._headers.get("Content-Length")
        if content_length_str is not None:
            try:
                content_length = int(content_length_str)
            except ValueError:
                self._fail(HttpProtocolError(
                    f"non-integer Content-Length: {content_length_str!r}",
                ))
                return
            if content_length < 0:
                self._fail(HttpProtocolError(
                    f"negative Content-Length: {content_length}",
                ))
                return
            if content_length > self._max_body_bytes:
                self._fail(HttpOversizedError(
                    f"Content-Length {content_length} exceeds cap "
                    f"{self._max_body_bytes}",
                ))
                return
            self._body_remaining = content_length
            if content_length == 0:
                self._state = ParseState.DONE
                return
            self._state = ParseState.BODY
            # Any bytes left in the buffer after the header CRLF are
            # the start of the body — flush into the body absorber.
            # MicroPython's bytearray lacks ``.clear()``; reassign to
            # a fresh empty bytearray instead (cross-runtime safe).
            if self._buffer:
                tail = bytes(self._buffer)
                self._buffer = bytearray()
                self._absorb_body_bytes(tail)
            return
        # Length-unknown — read until peer closes.
        self._body_remaining = -1
        self._state = ParseState.BODY
        if self._buffer:
            tail = bytes(self._buffer)
            self._buffer = bytearray()
            self._absorb_body_bytes(tail)

    def _absorb_body_bytes(self, chunk):
        """Append body bytes; honor the length cap and oversize policy."""
        if self._body_remaining == 0:
            return  # Already complete; ignore extra bytes (server bug).
        if self._body_remaining > 0:
            take = min(self._body_remaining, len(chunk))
            chunk = chunk[:take]
            self._body_remaining -= take
        # Length-unknown: enforce the max-body cap as we go.
        if (
            self._body_remaining < 0
            and len(self._body) + len(chunk) > self._max_body_bytes
        ):
            self._fail(HttpOversizedError(
                f"response body exceeded cap {self._max_body_bytes}",
            ))
            return
        self._body.extend(chunk)
        if self._body_remaining == 0:
            self._state = ParseState.DONE

    def _fail(self, error):
        """Latch *error* and transition to ERROR."""
        self._error = error
        self._state = ParseState.ERROR
