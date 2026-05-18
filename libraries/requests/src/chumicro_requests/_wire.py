"""HTTP/1.1 wire format for chumicro-requests.

Consolidates URL parsing, request encoding, response parsing, the
case-insensitive header dict, exception hierarchy, and protocol
constants.  Wire-format primitives live in one file
(bytes-on-the-wire); orchestration lives in another (``client.py``).

The response parser is a streaming state machine fed raw bytes via
:meth:`ResponseParser.feed`; it transitions
``STATUS -> HEADERS -> BODY -> DONE`` as bytes arrive.  No socket I/O
here — the client drives the socket and feeds bytes in.

v1 scope:

* HTTP and HTTPS via :mod:`chumicro_sockets` TLS.
* Body is buffered in full (capped by ``max_body_bytes``).
* ``Content-Length``-framed responses, read-until-close, and
  chunked transfer-encoding decode.
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
    chumicro-requests is single-in-flight — the caller must wait
    for ``handle.done`` before issuing another.
    """


class HttpURLError(HttpError):
    """URL doesn't parse as a supported HTTP/HTTPS URL."""


class HttpOversizedError(HttpError):
    """Response body exceeded ``max_body_bytes``.

    Raised when ``when_oversized=DISCONNECT``.  The other policies
    (``DROP_SILENT``, ``DROP_WITH_EVENT``) drop the payload silently
    or fire an event without raising.

    ``reported_length`` is the projected total body size at the moment
    the cap was crossed — useful when the error is re-raised to the
    caller under ``DISCONNECT``.
    """

    def __init__(self, message: str, *, reported_length: int) -> None:
        super().__init__(message)
        self.reported_length = reported_length


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default max buffered response body.  64 KB leaves headroom on a
#: 256 KB MCU RAM minimum board.
DEFAULT_MAX_BODY_BYTES = const(65536)

#: Default per-tick recv cap.  Mirrors :data:`chumicro_mqtt.MQTTClient`
#: default; keeps tick latency LED-friendly.
DEFAULT_RECV_BUDGET_PER_TICK = const(1024)

#: Default steady-state body buffer size for :class:`ResponseParser`.
#: Sized to cover typical sensor + JSON-API response bodies (most
#: small-board HTTP traffic) without per-request allocation.  Bodies
#: bigger than this fall back to a one-shot ``bytearray(content_length)``
#: that's released on the next :meth:`ResponseParser.reset`.  Matches
#: :data:`chumicro_websockets._wire.DEFAULT_PAYLOAD_BUFFER_SIZE` in shape.
DEFAULT_BODY_BUFFER_SIZE = const(1024)

#: Default per-request timeout in ms.
DEFAULT_TIMEOUT_MS = const(10000)

#: Default per-request redirect budget.
DEFAULT_MAX_REDIRECTS = const(5)

#: Status codes that the client follows when a ``Location`` header is
#: present and the per-request redirect budget allows.  301/302/303
#: switch the next request's method to ``GET`` (per RFC 7231 §6.4 +
#: long-standing browser behavior); 307/308 preserve the original
#: method and body.
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})

#: Subset of :data:`REDIRECT_STATUS_CODES` that preserve the original
#: HTTP method on the next hop (RFC 7231 §6.4.7 + §6.4.8 + RFC 7538).
METHOD_PRESERVING_REDIRECT_STATUS_CODES = frozenset({307, 308})

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
# Redirect URL resolution
# ---------------------------------------------------------------------------


def resolve_redirect_url(current_url: str, location: str) -> str:
    """Resolve a ``Location`` header value against the current request URL.

    Handles the three RFC 7231 §7.1.2 reference shapes:

    * **Absolute** — ``http://...`` / ``https://...``: returned verbatim.
    * **Absolute-path** — starts with ``/``: keeps current scheme + host
      + port, replaces path + query.
    * **Relative-path** — anything else: keeps current scheme + host +
      port, replaces the last path segment.

    Args:
        current_url: The URL of the request being redirected.
        location: The raw ``Location`` header value from the response.

    Returns:
        Absolute URL the redirected request should target.

    Raises:
        HttpURLError: *current_url* doesn't parse, or *location* is empty.
    """
    if not location:
        raise HttpURLError("redirect Location header is empty")
    if location.startswith("http://") or location.startswith("https://"):
        return location
    # Reject other absolute-URL schemes (`ftp://...`, `mailto:...`,
    # etc.) before they get misclassified as relative paths.  An
    # absolute URL has a scheme delimiter (``:``) before the first
    # path slash; relative paths never do.
    first_slash = location.find("/")
    scheme_zone = location if first_slash == -1 else location[:first_slash]
    if ":" in scheme_zone:
        raise HttpURLError(
            f"redirect Location has unsupported scheme: {location!r}",
        )
    scheme, host, port, current_path = parse_url(current_url)
    default_port = 443 if scheme == "https" else 80
    host_part = host if port == default_port else f"{host}:{port}"
    if location.startswith("/"):
        return f"{scheme}://{host_part}{location}"
    # Relative path — strip query from current path, then drop the
    # last segment, then join with the relative location.
    query_index = current_path.find("?")
    base_path = current_path[:query_index] if query_index != -1 else current_path
    last_slash = base_path.rfind("/")
    if last_slash == -1:
        base_path = "/"
    else:
        base_path = base_path[:last_slash + 1]
    return f"{scheme}://{host_part}{base_path}{location}"


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
        # Lowercase key -> (original_name, value).  Paired with
        # ``_order`` (list of lowercase keys) so iteration preserves
        # insertion order on every runtime — MicroPython and
        # CircuitPython dicts do not guarantee insertion order, unlike
        # CPython 3.7+.
        self._entries = {}
        self._order = []

    def __setitem__(self, name, value):
        lower = name.lower()
        if lower not in self._entries:
            self._order.append(lower)
        self._entries[lower] = (name, value)

    def __getitem__(self, name):
        return self._entries[name.lower()][1]

    def __contains__(self, name):
        return name.lower() in self._entries

    def __iter__(self):
        for lower in self._order:
            yield self._entries[lower][0]

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
        """Yield ``(original_name, value)`` pairs in insertion order."""
        for lower in self._order:
            yield self._entries[lower]

    def add(self, name, value):
        """Append *value* to the existing header, joining with ``, ``.

        New keys behave like :meth:`__setitem__`.  Used by the parser
        for repeated header lines (``Set-Cookie``, ``Via``).
        """
        lower = name.lower()
        existing = self._entries.get(lower)
        if existing is None:
            self._order.append(lower)
            self._entries[lower] = (name, value)
            return
        original_name, current_value = existing
        joined = f"{current_value}, {value}"
        self._entries[lower] = (original_name, joined)


# ---------------------------------------------------------------------------
# Request encoding
# ---------------------------------------------------------------------------


def _reject_control_chars(label: str, value: str) -> None:
    """Raise if *value* holds CR, LF, or NUL — HTTP request-splitting guards."""
    if "\r" in value or "\n" in value or "\x00" in value:
        raise HttpURLError(f"{label} contains a control character")


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
    # No gzip in v1; require identity from peers.
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

    # CR / LF / NUL in any request-line or header component would let a
    # caller-controlled value (path, header value) splice extra headers
    # or a second request onto the wire.  Reject before encoding.
    _reject_control_chars("method", method)
    _reject_control_chars("path", path)
    parts = [f"{method} {path} HTTP/1.1\r\n".encode("ascii")]
    for name, value in merged.items():
        _reject_control_chars("header name", str(name))
        _reject_control_chars("header value", str(value))
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

    Forward-only.  Two body framings::

      STATUS -> HEADERS -> BODY            -> DONE   (Content-Length / read-until-close)
      STATUS -> HEADERS -> CHUNK_SIZE
                            -> CHUNK_DATA
                            -> CHUNK_SIZE  (loop)
                            -> CHUNK_TRAILER
                            -> DONE                  (Transfer-Encoding: chunked)
                                              \\-> ERROR (any state)
    """

    STATUS = "status"
    HEADERS = "headers"
    BODY = "body"
    CHUNK_SIZE = "chunk_size"
    CHUNK_DATA = "chunk_data"
    CHUNK_TRAILER = "chunk_trailer"
    DONE = "done"
    ERROR = "error"


class ResponseParser:
    """Streaming HTTP/1.1 response parser.

    Fed raw bytes via :meth:`feed`; the state advances as soon as
    enough bytes have arrived.  Callers check :attr:`state` to know
    whether to keep feeding (anything other than ``DONE``/``ERROR``)
    or stop (``DONE``).

    Body framing:

    * ``Content-Length: N`` — read exactly N bytes.
    * ``Transfer-Encoding: chunked`` — RFC 7230 §4.1 chunked decode
      (slice 3f); chunk-extensions and trailers are accepted +
      discarded.
    * Neither header — read until the peer closes (signaled by
      :meth:`feed_eof`).

    The ``max_body_bytes`` cap is enforced incrementally — once total
    body bytes pass the cap the parser raises (or drops, depending on
    *when_oversized*) on the first :meth:`feed` past the threshold.
    """

    def __init__(
        self,
        *,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        body_buffer: bytearray | None = None,
        body_buffer_view: memoryview | None = None,
    ) -> None:
        """Construct a one-shot parser.

        Args:
            max_body_bytes: Hard cap on body size — bigger triggers the
                ``WhenOversized`` policy.
            body_buffer: Optional caller-owned ``bytearray`` to use as
                the steady-state body buffer.  When provided (typically
                by ``HttpClient`` so the buffer survives across requests),
                the parser writes into it for any response that fits.
                Oversized responses still allocate a one-shot
                ``bytearray(content_length)`` that's freed when the
                parser is garbage-collected.  When ``None``, the parser
                allocates its own ``bytearray(DEFAULT_BODY_BUFFER_SIZE)``
                — fine for one-shot users, but per-request churn for
                long-lived clients.
            body_buffer_view: Pre-cached ``memoryview(body_buffer)``
                supplied by the caller to avoid the parser constructing
                one.  Required when ``body_buffer`` is provided.
        """
        self._max_body_bytes = max_body_bytes
        self._buffer = bytearray()
        # Read cursor into ``_buffer``.  Each ``_consume(n)`` advances
        # the cursor and only reallocates the bytearray when at least
        # half of it has been consumed — amortizes the slice-reassign
        # idiom that used to fragment the heap on ESP32-class allocators.
        self._read_offset = 0
        self.state = ParseState.STATUS
        self.status_code = None
        self.reason = ""
        self.http_version = ""
        self.headers = CaseInsensitiveDict()
        # Body buffer: caller-supplied (HttpClient passes its long-
        # lived buffer for cross-request reuse) or self-allocated
        # (standalone use).  Either way ``_body`` is the active buffer
        # and ``_body_view`` the cached memoryview.  Oversized responses
        # (Content-Length > capacity) rebind ``_body`` to a one-shot
        # ``bytearray(content_length)`` that gets freed when the parser
        # is dereferenced.
        if body_buffer is not None:
            if body_buffer_view is None:
                body_buffer_view = memoryview(body_buffer)
            self._body = body_buffer
            self._body_view = body_buffer_view
            self._body_capacity = len(body_buffer)
        else:
            # No external buffer — start empty and grow on demand.
            # Pre-allocating a fixed N-byte default per parser instance
            # would put a tier-N alloc/free cycle on every standalone
            # use (the on-device fragmentation tests caught this:
            # ``test_small_body`` and ``test_large_body`` regressed with
            # a 1024-byte default).  Geometric growth via ``extend``
            # primes the small allocator tiers along the way, which the
            # allocator can recycle cleanly between iterations.  When
            # the consumer is long-lived (``HttpClient``), it should
            # pass ``body_buffer`` so the steady-state buffer is shared
            # across requests instead of reallocated per-instance.
            self._body = bytearray()
            self._body_view = memoryview(self._body)
            self._body_capacity = 0
        self._body_write_offset = 0
        # -1 = unknown (read until close).  Set to a non-negative
        # value when Content-Length parses successfully.
        self._body_remaining = -1
        # Bytes left in the current chunk (chunked decode only).
        self._chunk_remaining = 0
        self.error = None

    # ------------------------------------------------------------------
    # Buffer helpers (read-cursor pattern)
    # ------------------------------------------------------------------

    def _live_len(self):
        """Number of unconsumed bytes in ``_buffer``."""
        return len(self._buffer) - self._read_offset

    def _live_find(self, target):
        """``find`` *target* in the unconsumed region; returns relative position or -1."""
        position = self._buffer.find(target, self._read_offset)
        if position == -1:
            return -1
        return position - self._read_offset

    def _live_slice(self, start, end=None):
        """Slice of unconsumed data.  Indices are relative to the cursor."""
        absolute_start = self._read_offset + start
        if end is None:
            return self._buffer[absolute_start:]
        return self._buffer[absolute_start:absolute_start + end]

    def _consume(self, count):
        """Advance the read cursor by *count* bytes; compact when the cursor
        passes the halfway mark.

        Compaction uses slice-assign-empty (``self._buffer[:offset] = b""``)
        — in-place memmove on CPython, MicroPython, and CircuitPython
        (``mp_seq_replace_slice_no_grow``).  No allocation, no realloc.
        The earlier shape ``self._buffer = bytearray(self._buffer[offset:])``
        allocated a fresh bytearray per compaction; benchmarks on Lolin S2
        traced the 1024-byte-tier fragmentation it caused to that path.
        Mirrors the in-place compact pattern in
        ``chumicro_mqtt._wire.PacketDecoder._consume``.
        """
        self._read_offset += count
        if self._read_offset > 0 and self._read_offset * 2 >= len(self._buffer):
            self._buffer[:self._read_offset] = b""
            self._read_offset = 0

    def _reset_buffer(self):
        """Drop every buffered byte and reset the cursor."""
        self._buffer = bytearray()
        self._read_offset = 0

    # ------------------------------------------------------------------
    # Public observation
    # ------------------------------------------------------------------

    @property
    def body(self):
        """Body bytes received so far (final once :attr:`state` is ``DONE``).

        Reads through the cached ``_body_view`` (zero-copy memoryview
        slice) and snapshots one ``bytes`` copy for the caller —
        ``Response.text`` calls ``.decode()`` on the result, which
        memoryview lacks.
        """
        return bytes(self._body_view[:self._body_write_offset])

    # ------------------------------------------------------------------
    # Driving the parser
    # ------------------------------------------------------------------

    def feed(self, chunk):
        """Append *chunk* to the parser's buffer and advance the state.

        Raises :class:`HttpProtocolError` (or :class:`HttpOversizedError`)
        when the bytes can't be reconciled with HTTP/1.1.
        """
        if self.state in (ParseState.DONE, ParseState.ERROR):
            return
        if chunk:
            if self.state == ParseState.BODY:
                # Skip the staging buffer for length-known/-unknown body
                # bytes — straight in.  Chunked decode flows through the
                # state machine via _buffer because each chunk is framed.
                self._absorb_body_bytes(chunk)
            else:
                self._buffer.extend(chunk)
        self._advance()

    def feed_eof(self):
        """Signal that the peer closed the connection.

        For a ``Content-Length``-framed response this is a protocol
        error if the body was short.  For a length-unknown response
        (no ``Content-Length``, no ``Transfer-Encoding``) this is the
        normal end-of-body signal.  Mid-chunk it's always an error —
        chunked encoding is self-terminating.
        """
        if self.state == ParseState.DONE:
            return
        if self.state == ParseState.ERROR:
            return
        if self.state == ParseState.BODY and self._body_remaining < 0:
            # Length-unknown body; peer-close == done.
            self.state = ParseState.DONE
            return
        if self.state == ParseState.BODY and self._body_remaining > 0:
            self._fail(HttpProtocolError(
                f"peer closed mid-body; {self._body_remaining} bytes "
                "still expected per Content-Length",
            ))
            return
        if self.state in (
            ParseState.CHUNK_SIZE, ParseState.CHUNK_DATA, ParseState.CHUNK_TRAILER,
        ):
            self._fail(HttpProtocolError(
                f"peer closed mid-chunked-body (state={self.state})",
            ))
            return
        # Mid-headers or mid-status — peer hung up before responding.
        self._fail(HttpProtocolError(
            f"peer closed before response completed (state={self.state})",
        ))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _advance(self):
        """Consume buffered bytes until no more progress is possible."""
        while True:
            if self.state == ParseState.STATUS:
                if not self._try_parse_status_line():
                    return
                continue
            if self.state == ParseState.HEADERS:
                if not self._try_parse_headers():
                    return
                continue
            if self.state == ParseState.CHUNK_SIZE:
                if not self._try_parse_chunk_size():
                    return
                continue
            if self.state == ParseState.CHUNK_DATA:
                if not self._try_consume_chunk_data():
                    return
                continue
            if self.state == ParseState.CHUNK_TRAILER:
                if not self._try_parse_chunk_trailer():
                    return
                continue
            return  # BODY (handled in feed) / DONE / ERROR

    def _try_parse_status_line(self):
        """Consume one status line; return True if state advanced."""
        crlf_index = self._live_find(CRLF)
        if crlf_index == -1:
            return False
        line = self._live_slice(0, crlf_index)
        self._consume(crlf_index + 2)
        # Status-Line per RFC 7230 §3.1.2: HTTP-version SP status-code SP reason-phrase
        try:
            text = str(line, "ascii")
        except UnicodeError as decode_error:
            self._fail(HttpProtocolError(
                f"non-ASCII status line: {bytes(line)!r}",
            ))
            raise self.error from decode_error
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
            self.status_code = int(code_str)
        except ValueError:
            self._fail(HttpProtocolError(
                f"non-integer status code: {code_str!r}",
            ))
            return True
        self.http_version = version_str
        self.reason = parts[2] if len(parts) == 3 else ""
        self.state = ParseState.HEADERS
        return True

    def _try_parse_headers(self):
        """Consume one header line; return True if state advanced or
        another header was parsed."""
        crlf_index = self._live_find(CRLF)
        if crlf_index == -1:
            return False
        if crlf_index == 0:
            # Empty line — end of headers.
            self._consume(2)
            self._enter_body_state()
            return True
        line = self._live_slice(0, crlf_index)
        self._consume(crlf_index + 2)
        try:
            text = str(line, "ascii")
        except UnicodeError as decode_error:
            self._fail(HttpProtocolError(
                f"non-ASCII header line: {bytes(line)!r}",
            ))
            raise self.error from decode_error
        colon_index = text.find(":")
        if colon_index <= 0:
            self._fail(HttpProtocolError(
                f"header line missing ':' or empty name: {text!r}",
            ))
            return True
        name = text[:colon_index]
        value = text[colon_index + 1:].strip()
        self.headers.add(name, value)
        return True

    def _enter_body_state(self):
        """Headers-complete: figure out body framing."""
        if self.status_code in NO_BODY_STATUS_CODES or (
            100 <= self.status_code < 200
        ):
            self.state = ParseState.DONE
            return
        # Transfer-Encoding takes precedence over Content-Length per
        # RFC 7230 §3.3.3 — when both are present, the framing is
        # chunked and Content-Length is informational only.
        transfer_encoding = self.headers.get("Transfer-Encoding")
        if transfer_encoding is not None:
            # We accept "chunked" as the final (or only) coding.  Other
            # transfer codings (gzip, deflate, identity stacked with
            # chunked) aren't supported in v1 — reject as protocol error
            # so the caller doesn't silently get garbled bytes.
            normalized = transfer_encoding.replace(" ", "").lower()
            if normalized != "chunked":
                self._fail(HttpProtocolError(
                    f"unsupported Transfer-Encoding: {transfer_encoding!r} "
                    "(only 'chunked' is supported in v1)",
                ))
                return
            self.state = ParseState.CHUNK_SIZE
            return
        content_length_str = self.headers.get("Content-Length")
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
                    reported_length=content_length,
                ))
                return
            self._body_remaining = content_length
            if content_length == 0:
                self.state = ParseState.DONE
                return
            self.state = ParseState.BODY
            self._body_write_offset = 0
            # Don't pre-allocate the body upfront: the absorb path
            # handles growth via doubling-grow (one-shot realloc when
            # the write would overflow current capacity).  When the
            # consumer supplied an external ``body_buffer`` and the
            # response fits, no allocation happens at all.  When no
            # external buffer was supplied, geometric grow primes the
            # small allocator tiers along the way — measured cleaner on
            # MicroPython than a single tier-N alloc/free cycle per
            # request (on-device fragmentation tests caught this).
            # Any bytes left in the buffer after the header CRLF are
            # the start of the body — flush into the body absorber.
            if self._live_len() > 0:
                tail_view = self._live_slice(0)
                self._reset_buffer()
                self._absorb_body_bytes(tail_view)
            return
        # Length-unknown — read until peer closes.
        self._body_remaining = -1
        self.state = ParseState.BODY
        if self._live_len() > 0:
            tail = bytes(self._live_slice(0))
            self._reset_buffer()
            self._absorb_body_bytes(tail)

    def _try_parse_chunk_size(self):
        """Consume one chunk-size line; return True if state advanced.

        Format per RFC 7230 §4.1.1::

            chunk-size [ ";" chunk-ext ] CRLF

        chunk-extensions are accepted and ignored.  A size of 0 marks
        the last-chunk and transitions to CHUNK_TRAILER.
        """
        crlf_index = self._live_find(CRLF)
        if crlf_index == -1:
            return False
        line = self._live_slice(0, crlf_index)
        self._consume(crlf_index + 2)
        try:
            text = str(line, "ascii")
        except UnicodeError as decode_error:
            self._fail(HttpProtocolError(
                f"non-ASCII chunk-size line: {bytes(line)!r}",
            ))
            raise self.error from decode_error
        # Strip chunk-extensions (everything after the first ';').
        semicolon_index = text.find(";")
        size_text = text[:semicolon_index] if semicolon_index != -1 else text
        size_text = size_text.strip()
        if not size_text:
            self._fail(HttpProtocolError(
                f"empty chunk-size line: {line!r}",
            ))
            return True
        try:
            chunk_size = int(size_text, 16)
        except ValueError:
            self._fail(HttpProtocolError(
                f"non-hex chunk-size: {size_text!r}",
            ))
            return True
        if chunk_size < 0:
            self._fail(HttpProtocolError(
                f"negative chunk-size: {chunk_size}",
            ))
            return True
        # Enforce the max-body cap as the chunk sizes accumulate so a
        # malicious server can't trickle in 64K + 1B before we notice.
        if self._body_write_offset + chunk_size > self._max_body_bytes:
            self._fail(HttpOversizedError(
                f"chunked body would exceed cap {self._max_body_bytes}",
                reported_length=self._body_write_offset + chunk_size,
            ))
            return True
        if chunk_size == 0:
            self.state = ParseState.CHUNK_TRAILER
            return True
        # No upfront body alloc needed — the steady-state buffer is
        # already in place from :meth:`__init__` / :meth:`reset`.
        # Chunks that fit write in place; chunks that overflow trigger
        # a one-shot grow in :meth:`_try_consume_chunk_data`.
        self._chunk_remaining = chunk_size
        self.state = ParseState.CHUNK_DATA
        return True

    def _try_consume_chunk_data(self):
        """Consume up to ``_chunk_remaining`` bytes + the trailing CRLF.

        Returns True when state advances (data fully consumed +
        terminating CRLF parsed) so :meth:`_advance` keeps walking.
        Returns False when there's not enough buffered to make
        progress — caller waits for the next :meth:`feed`.

        Body writes use slice-assign at ``_body_write_offset``: in-place
        when the offset+take fits inside the pre-allocated buffer
        (single-chunk hot path), implicit-resize when it doesn't (multi-
        chunk grow path — ``bytearray[N:N] = data`` extends).
        """
        if self._chunk_remaining > 0:
            available = min(self._chunk_remaining, self._live_len())
            if available == 0:
                return False
            source = memoryview(self._buffer)[
                self._read_offset:self._read_offset + available
            ]
            self._absorb_body_chunk(source)
            # Drop the memoryview before _consume's in-place compaction.
            # CPython refuses to resize a bytearray with active exports
            # (BufferError); releasing the view here lets _consume's
            # slice-assign-empty memmove run.  MicroPython / CircuitPython
            # don't track exports, so this is defensive on those runtimes.
            source = None
            self._consume(available)
            self._chunk_remaining -= available
            if self._chunk_remaining > 0:
                return False
        # Chunk data exhausted; expect a terminating CRLF before the
        # next chunk-size line.
        if self._live_len() < 2:
            return False
        tail = self._live_slice(0, 2)
        if tail != CRLF:
            self._fail(HttpProtocolError(
                f"missing CRLF after chunk data: {bytes(tail)!r}",
            ))
            return True
        self._consume(2)
        self.state = ParseState.CHUNK_SIZE
        return True

    def _try_parse_chunk_trailer(self):
        """Consume optional trailer header lines until the empty CRLF.

        v1 ignores trailer values — they're rare and most consumers
        don't care.  When the empty line arrives the body is complete
        and we transition to DONE.
        """
        crlf_index = self._live_find(CRLF)
        if crlf_index == -1:
            return False
        if crlf_index == 0:
            # Empty trailer line — end of chunked body.
            self._consume(2)
            self.state = ParseState.DONE
            return True
        # Non-empty trailer line — discard (RFC 7230 §4.1.2 lets us
        # ignore trailers we don't recognize).
        self._consume(crlf_index + 2)
        return True

    def _absorb_body_bytes(self, chunk):
        """Append body bytes; honor the length cap and oversize policy.

        Two paths:

        * **External buffer in use** (``_body_capacity > 0``): the
          buffer is the shared steady-state (see ``__init__``);
          slice-assign at ``_body_write_offset`` writes in place.
          When the response exceeds capacity, allocate a one-shot
          replacement (drops on parser GC).

        * **Default (no external buffer, ``_body_capacity == 0``)**:
          use ``bytearray.extend`` so the body grows through the
          allocator's internal geometric tiers (16, 32, 64, …) rather
          than landing each grow exactly on the round-number tiers
          (256, 1024) that the on-device fragmentation tests measure.
          The view cache is refreshed lazily because extend invalidates
          the prior memoryview.
        """
        if self._body_remaining == 0:
            return  # Already complete; ignore extra bytes (server bug).
        if self._body_remaining > 0:
            take = min(self._body_remaining, len(chunk))
            self._absorb_body_chunk(chunk[:take] if take < len(chunk) else chunk)
            self._body_remaining -= take
            if self._body_remaining == 0:
                self.state = ParseState.DONE
            return
        # Length-unknown: enforce the max-body cap as we go.
        chunk_len = len(chunk)
        if self._body_write_offset + chunk_len > self._max_body_bytes:
            self._fail(HttpOversizedError(
                f"response body exceeded cap {self._max_body_bytes}",
                reported_length=self._body_write_offset + chunk_len,
            ))
            return
        self._absorb_body_chunk(chunk)

    def _absorb_body_chunk(self, chunk):
        """Write *chunk* at the current body write cursor.

        Slice-assign when the write fits inside the current body
        capacity (the steady-state path when an external buffer was
        supplied or after the body was pre-allocated to ``Content-
        Length``), or one-shot replace when it doesn't (chunked /
        length-unknown grow path).  Never uses ``bytearray.extend`` —
        that's "alloc bigger + memcpy old + memcpy new + free old"
        on CP / MP, three allocations per logical write.
        """
        chunk_len = len(chunk)
        write_offset = self._body_write_offset
        end_offset = write_offset + chunk_len
        if end_offset <= len(self._body_view):
            # Fits inside current capacity — in-place slice-assign.
            self._body[write_offset:end_offset] = chunk
        else:
            # Grow path: allocate exact-size replacement, copy existing
            # data, write the new chunk.  Skips the extend reallocation
            # cost; the caller's external buffer (if any) is left
            # untouched because we rebind ``_body`` to the one-shot.
            new_body = bytearray(end_offset)
            new_body[:write_offset] = self._body_view[:write_offset]
            new_body[write_offset:end_offset] = chunk
            self._body = new_body
            self._body_view = memoryview(new_body)
            if self._body_capacity == 0:
                # Track the grown size so the next grow check works.
                self._body_capacity = end_offset
            else:
                # External buffer was overflowed — replaced for this
                # request only; the caller's ``body_buffer`` reference
                # is unchanged and gets used again next request.
                self._body_capacity = end_offset
        self._body_write_offset = end_offset

    def _fail(self, error):
        """Latch *error* and transition to ERROR."""
        self.error = error
        self.state = ParseState.ERROR
