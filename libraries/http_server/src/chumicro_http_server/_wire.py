"""HTTP/1.1 wire format for chumicro-http-server.

Server-side counterpart to :mod:`chumicro_requests._wire`: a streaming
:class:`RequestParser` reads the request line + headers (+ optional
body) one chunk at a time, fed bytes by the per-connection state
machine in ``server.py``.

The shared HTTP/1.1 primitives needed by both client and server —
:class:`CaseInsensitiveDict` (case-insensitive header dict, RFC 7230
§3.2) and :func:`parse_charset` (Content-Type charset, RFC 7231
§3.1.1.5) — are inlined here rather than imported from
:mod:`chumicro_requests`: pulling the full client (~1.8K lines)
onto server-only boards for ~125 lines of shared code roughly
doubles the flash footprint of a server-only deploy.  The RFCs
are stable, so the duplication has near-zero drift cost.

Scope: request line + headers + ``Content-Length`` body buffering.
Chunked request bodies and streaming-via-chunk-callback are out of
scope.
"""

try:
    from micropython import const
except ImportError:
    def const(value):
        return value


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default per-connection recv cap.
DEFAULT_RECV_BUDGET_PER_TICK = const(1024)

#: Default per-connection send cap.
DEFAULT_SEND_BUDGET_PER_TICK = const(4096)

#: Default per-request body cap.  Bodies bigger than this are rejected
#: at headers-complete time with a 413 response — no body allocation.
DEFAULT_MAX_REQUEST_BODY_BYTES = const(16384)

#: Default steady-state body buffer size for :class:`RequestParser`.
#: The Connection layer allocates one of these per accepted connection
#: and passes it to the parser, so requests whose Content-Length fits
#: parse with zero body allocation; larger requests get a one-shot
#: ``bytearray(content_length)`` sized-to-fit, freed after the response
#: drains.  Matches :data:`chumicro_requests._wire.DEFAULT_BODY_BUFFER_SIZE`.
DEFAULT_BODY_BUFFER_SIZE = const(1024)

#: Default per-connection deadline.
DEFAULT_REQUEST_TIMEOUT_MS = const(10000)

#: Default in-flight connection cap.
DEFAULT_MAX_CONNECTIONS = const(4)

#: HTTP/1.1 line terminator.
CRLF = b"\r\n"


# ---------------------------------------------------------------------------
# Server-facing exceptions
# ---------------------------------------------------------------------------


class ServerError(Exception):
    """Base class for chumicro-http-server failures.

    Independent of :mod:`chumicro_requests`'s ``HttpError`` so the
    server can ship without the client library.  Callers that run
    both halves on one board and want to catch either side can use
    ``except (HttpError, ServerError):``.
    """


class ServerProtocolError(ServerError):
    """Inbound bytes don't conform to HTTP/1.1.

    Connection should be torn down + a 400 returned (best-effort).
    """


class ServerOversizedError(ServerError):
    """Request ``Content-Length`` exceeds ``max_body_bytes``.

    Surfaced by the parser at headers-complete time, before any body
    bytes are allocated.  The connection layer responds with 413
    Payload Too Large and closes — the body is never read.  Sibling
    of :class:`ServerProtocolError` so ``except ServerError`` catches
    both, but distinct so the connection can choose 413 over 400.

    :attr:`reported_length` is the value the client declared.
    """

    def __init__(self, message, *, reported_length):
        super().__init__(message)
        self.reported_length = reported_length


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
    per RFC 7230 §3.2.2 when the same header arrives twice.

    Implements ``__getitem__`` / ``__setitem__`` / ``__contains__`` /
    ``__len__`` / ``__iter__`` / ``get`` / ``items`` — enough for the
    request/response API surface.  Not a full :class:`MutableMapping`
    to keep the embedded footprint small.

    Inlined from chumicro-requests to keep the server self-contained;
    behavior matches :class:`chumicro_requests.CaseInsensitiveDict`
    byte-for-byte.
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

    Inlined from chumicro-requests to keep the server self-contained;
    behavior matches :func:`chumicro_requests.parse_charset`
    byte-for-byte.

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
# Request parser
# ---------------------------------------------------------------------------


class RequestParseState:
    """Streaming request parser states.

    Forward-only::

      REQUEST_LINE -> HEADERS -> BODY -> DONE
                                   \\-> ERROR (any state)
    """

    REQUEST_LINE = "request_line"
    HEADERS = "headers"
    BODY = "body"
    DONE = "done"
    ERROR = "error"


class RequestParser:
    """Streaming HTTP/1.1 request parser.

    Fed raw bytes via :meth:`feed`; the state advances as soon as
    enough bytes arrive.  Callers check :attr:`state` to know whether
    to keep feeding (anything other than ``DONE``/``ERROR``) or stop.

    Body framing — two active tiers + a steady-state tier reserved
    for keep-alive (parallel to :class:`chumicro_requests._wire.
    HttpResponseParser`'s shape):

    * **Sized rebind.**  ``Content-Length ≤ max_body_bytes`` but >
      ``body_buffer`` capacity (default capacity is 0, since
      ``body_buffer`` is unused by ``_Connection`` today).  The parser
      allocates one ``bytearray(content_length)`` sized exactly to
      fit at headers-complete time and slice-assigns body bytes
      directly into it.  Single allocation per request, freed when
      the parser is dereferenced.
    * **413 reject.**  ``Content-Length > max_body_bytes``.  No body
      allocation.  Parser raises :class:`ServerOversizedError` and
      the connection layer responds 413 Payload Too Large.
    * **Steady (reserved).**  ``Content-Length ≤ body_buffer
      capacity``.  Body writes land in the caller-supplied buffer
      with zero allocation.  ``_Connection`` does not supply a
      ``body_buffer`` today because every response emits
      ``Connection: close`` — the buffer would have a use-once
      lifetime, which the on-device fragmentation tests in
      ``chumicro_requests`` measured as a regression.  When
      keep-alive lands and connections live across requests, the
      buffer becomes a steady-state tier worth pre-allocating.

    Chunked request bodies are not supported, so Content-Length is
    always known when entering ``BODY`` state — sized-rebind happens
    at :meth:`_enter_body_state`, not lazily during body absorption.

    No Content-Length and no chunked → assume zero-length body,
    transition straight to ``DONE``.
    """

    def __init__(
        self,
        *,
        max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES,
        body_buffer: bytearray | None = None,
        body_buffer_view: memoryview | None = None,
    ) -> None:
        """Construct a one-shot parser.

        Args:
            max_body_bytes: Hard cap on body size — exceeded ⇒ 413.
            body_buffer: Optional caller-owned ``bytearray`` reused as
                a steady-state body buffer across requests.  Requests
                whose Content-Length fits land in it with zero
                allocation; bigger-but-allowed requests rebind ``_body``
                to a one-shot sized-to-fit buffer for that request only
                and leave the caller's reference unchanged.  ``None``
                (the default, and what ``_Connection`` passes today)
                means the parser starts empty and the sized-rebind
                path allocates fresh for every body.  Pre-allocating
                a buffer that has a use-once lifetime fragments worse
                than allocating sized-to-fit on demand (measured by
                the on-device fragmentation tests in
                ``chumicro_requests``); only supply ``body_buffer``
                when its lifetime truly spans multiple requests.
            body_buffer_view: Pre-cached ``memoryview(body_buffer)``
                supplied by the caller to avoid the parser constructing
                one.  Optional even when ``body_buffer`` is provided
                (a view will be made if missing).
        """
        self._max_body_bytes = max_body_bytes
        self._buffer = bytearray()
        # Read cursor into ``_buffer``.  Each ``_consume(n)`` advances
        # the cursor and only realloates the bytearray when at least
        # half of it has been consumed — mirrors the read-cursor pattern
        # in :class:`chumicro_requests._wire.HttpResponseParser`.
        self._read_offset = 0
        self.state = RequestParseState.REQUEST_LINE
        self.method = ""
        self.target = ""
        self.http_version = ""
        self.headers = CaseInsensitiveDict()
        # Body buffer: caller-supplied (``_Connection`` passes the
        # long-lived per-connection buffer) or self-allocated (standalone
        # use starts empty + rebinds on first request).  ``_body`` is
        # the active buffer, ``_body_view`` the cached memoryview,
        # ``_body_capacity`` the size of the active buffer.  Oversized
        # but-allowed requests (capacity < Content-Length ≤ max_body_bytes)
        # rebind ``_body`` in :meth:`_enter_body_state`.
        if body_buffer is not None:
            if body_buffer_view is None:
                body_buffer_view = memoryview(body_buffer)
            self._body = body_buffer
            self._body_view = body_buffer_view
            self._body_capacity = len(body_buffer)
        else:
            self._body = bytearray()
            self._body_view = memoryview(self._body)
            self._body_capacity = 0
        self._body_write_offset = 0
        self._body_remaining = 0
        self.error = None

    # ------------------------------------------------------------------
    # Buffer helpers (read-cursor pattern — see ResponseParser)
    # ------------------------------------------------------------------

    def _live_len(self):
        """Number of unconsumed bytes in ``_buffer``."""
        return len(self._buffer) - self._read_offset

    def _live_find(self, target):
        """``find`` *target* in the unconsumed region; relative position or -1."""
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
        """Advance the cursor; compact when past the halfway mark.

        Slice-assign-empty (``self._buffer[:offset] = b""``) does an
        in-place memmove on CPython / MicroPython / CircuitPython — no
        allocation.  See :meth:`chumicro_requests._wire.ResponseParser._consume`
        for the fragmentation rationale and the original allocating shape
        this replaces.
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
    #
    # ``state`` / ``method`` / ``target`` / ``http_version`` / ``headers`` /
    # ``error`` are direct public attributes set during parsing.  The body
    # snapshot needs a computed view, so it stays a method-shape accessor.

    @property
    def body(self):
        """Body bytes received so far (final once :attr:`state` is ``DONE``).

        Reads through the cached ``_body_view`` (zero-copy memoryview
        slice) and snapshots one ``bytes`` copy for the caller —
        handlers may ``.decode()`` the result, which memoryview lacks.
        """
        return bytes(self._body_view[:self._body_write_offset])

    # ------------------------------------------------------------------
    # Driving the parser
    # ------------------------------------------------------------------

    def feed(self, chunk):
        """Append *chunk* to the parser's buffer and advance the state.

        Raises :class:`ServerProtocolError` when the bytes can't be
        reconciled with HTTP/1.1.
        """
        if self.state in (RequestParseState.DONE, RequestParseState.ERROR):
            return
        if chunk:
            if self.state == RequestParseState.BODY:
                self._absorb_body_bytes(chunk)
            else:
                self._buffer.extend(chunk)
        self._advance()

    def feed_eof(self):
        """Signal that the peer closed.  Mid-headers is a protocol error."""
        if self.state in (RequestParseState.DONE, RequestParseState.ERROR):
            return
        if self.state == RequestParseState.BODY and self._body_remaining > 0:
            self._fail(ServerProtocolError(
                f"client closed mid-body; {self._body_remaining} bytes "
                "still expected per Content-Length",
            ))
            return
        self._fail(ServerProtocolError(
            f"client closed before request completed (state={self.state})",
        ))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _advance(self):
        """Consume buffered bytes until no more progress is possible."""
        while True:
            if self.state == RequestParseState.REQUEST_LINE:
                if not self._try_parse_request_line():
                    return
                continue
            if self.state == RequestParseState.HEADERS:
                if not self._try_parse_headers():
                    return
                continue
            return  # BODY (handled in feed) / DONE / ERROR

    def _try_parse_request_line(self):
        """Consume the request line; return True if state advanced.

        Format per RFC 7230 §3.1.1::

            method SP request-target SP HTTP-version CRLF
        """
        crlf_index = self._live_find(CRLF)
        if crlf_index == -1:
            return False
        line = self._live_slice(0, crlf_index)
        self._consume(crlf_index + 2)
        try:
            text = str(line, "ascii")
        # HTTP/1.1 §3.1 forbids non-ASCII; defensive only.
        except UnicodeDecodeError as decode_error:  # pragma: no cover
            self._fail(ServerProtocolError(
                f"non-ASCII request line: {bytes(line)!r}",
            ))
            raise self.error from decode_error
        parts = text.split(" ")
        if len(parts) != 3:
            self._fail(ServerProtocolError(
                f"malformed request line: {text!r}",
            ))
            return True
        method, target, version_str = parts
        if not version_str.startswith("HTTP/"):
            self._fail(ServerProtocolError(
                f"request line missing HTTP version: {text!r}",
            ))
            return True
        if not method:
            self._fail(ServerProtocolError(
                f"empty method: {text!r}",
            ))
            return True
        if not target:
            self._fail(ServerProtocolError(
                f"empty request-target: {text!r}",
            ))
            return True
        self.method = method
        self.target = target
        self.http_version = version_str
        self.state = RequestParseState.HEADERS
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
        # HTTP/1.1 §3.2 forbids non-ASCII; defensive only.
        except UnicodeDecodeError as decode_error:  # pragma: no cover
            self._fail(ServerProtocolError(
                f"non-ASCII header line: {bytes(line)!r}",
            ))
            raise self.error from decode_error
        colon_index = text.find(":")
        if colon_index <= 0:
            self._fail(ServerProtocolError(
                f"header line missing ':' or empty name: {text!r}",
            ))
            return True
        name = text[:colon_index]
        value = text[colon_index + 1:].strip()
        self.headers.add(name, value)
        return True

    def _enter_body_state(self):
        """Headers-complete: figure out body framing + size the body buffer."""
        if self.headers.get("Transfer-Encoding") is not None:
            # Chunked request bodies are unsupported; framing one as
            # zero-length (the no-Content-Length path below) lets a
            # smuggled body ride into the next request. Reject (400).
            self._fail(ServerProtocolError(
                "Transfer-Encoding request bodies are not supported",
            ))
            return
        content_length_str = self.headers.get("Content-Length")
        if content_length_str is None:
            # No Content-Length, no chunked — assume zero body.
            self.state = RequestParseState.DONE
            return
        try:
            content_length = int(content_length_str)
        except ValueError:
            self._fail(ServerProtocolError(
                f"non-integer Content-Length: {content_length_str!r}",
            ))
            return
        if content_length < 0:
            self._fail(ServerProtocolError(
                f"negative Content-Length: {content_length}",
            ))
            return
        if content_length > self._max_body_bytes:
            # Tier 3: 413 before any body allocation.  The connection
            # layer catches ``ServerOversizedError`` and responds 413
            # rather than treating it as a generic protocol-error 400.
            self._fail(ServerOversizedError(
                f"Content-Length {content_length} exceeds cap "
                f"{self._max_body_bytes}",
                reported_length=content_length,
            ))
            return
        self._body_remaining = content_length
        if content_length == 0:
            self.state = RequestParseState.DONE
            return
        # Tier 2 sized-rebind when the steady buffer (caller-supplied
        # or empty) can't hold this request.  Tier 1 — when capacity
        # already covers ``content_length`` — touches no heap.
        if content_length > self._body_capacity:
            self._body = bytearray(content_length)
            self._body_view = memoryview(self._body)
            self._body_capacity = content_length
        self.state = RequestParseState.BODY
        self._body_write_offset = 0
        if self._live_len() > 0:
            tail_view = self._live_slice(0)
            self._reset_buffer()
            self._absorb_body_bytes(tail_view)

    def _absorb_body_bytes(self, chunk):
        """Write body bytes into the pre-sized body buffer.

        :meth:`_enter_body_state` already sized ``_body`` to the
        declared Content-Length (the steady-state buffer when it fits,
        a one-shot sized-rebind otherwise), so every write here fits
        and slice-assign is unconditional.  No grow fallback.
        """
        if self._body_remaining == 0:
            return  # Already complete; ignore extra (client sent too many).
        take = min(self._body_remaining, len(chunk))
        write_offset = self._body_write_offset
        end_offset = write_offset + take
        source = chunk[:take] if take < len(chunk) else chunk
        self._body[write_offset:end_offset] = source
        self._body_write_offset = end_offset
        self._body_remaining -= take
        if self._body_remaining == 0:
            self.state = RequestParseState.DONE

    def _fail(self, error):
        """Latch *error* and transition to ERROR."""
        self.error = error
        self.state = RequestParseState.ERROR


# ---------------------------------------------------------------------------
# Request-target helpers
# ---------------------------------------------------------------------------


def split_target(target: str) -> tuple[str, str]:
    """Split a request-target into ``(path, raw_query)``.

    *path* always starts with ``/`` (matches the request-target shape
    HTTP clients use).  *raw_query* is everything after the first ``?``
    or ``""`` when none is present — caller parses further with
    :func:`parse_query` if needed.
    """
    question_index = target.find("?")
    if question_index == -1:
        return target, ""
    return target[:question_index], target[question_index + 1:]


def parse_query(raw_query: str) -> "CaseInsensitiveDict":
    """Parse a ``foo=bar&baz=qux`` query string into a header-shaped dict.

    Repeated keys join with ``,`` per the same RFC 7230 §3.2.2 rule
    headers use — caller can `.split(",")` if they need both values.
    Percent-decoding is **not** done in v1; URL-encoded values come
    through as-is (most embedded REST APIs use bare alphanumeric
    keys + values).  Documented as a limitation.
    """
    result = CaseInsensitiveDict()
    if not raw_query:
        return result
    for pair in raw_query.split("&"):
        if not pair:
            continue
        equals_index = pair.find("=")
        if equals_index == -1:
            name = pair
            value = ""
        else:
            name = pair[:equals_index]
            value = pair[equals_index + 1:]
        if name:
            result.add(name, value)
    return result


# Re-export the shared primitive so server-side callers don't need to
# also import from chumicro_requests.
__all__ = [
    "CRLF",
    "DEFAULT_BODY_BUFFER_SIZE",
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_MAX_REQUEST_BODY_BYTES",
    "DEFAULT_RECV_BUDGET_PER_TICK",
    "DEFAULT_REQUEST_TIMEOUT_MS",
    "DEFAULT_SEND_BUDGET_PER_TICK",
    "CaseInsensitiveDict",
    "RequestParseState",
    "RequestParser",
    "ServerError",
    "ServerOversizedError",
    "ServerProtocolError",
    "parse_charset",
    "parse_query",
    "split_target",
]
