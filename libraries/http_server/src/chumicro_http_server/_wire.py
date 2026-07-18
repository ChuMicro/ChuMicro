"""HTTP/1.1 wire format for chumicro-http-server.

A streaming :class:`RequestParser` reads the request line, headers, and
optional ``Content-Length`` body one chunk at a time, fed by the
per-connection state machine in ``server.py``. Chunked request bodies are
out of scope.
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

#: Default per-request body cap. Bigger bodies are rejected with a 413.
DEFAULT_MAX_REQUEST_BODY_BYTES = const(16384)

#: Default cap on the request-line length (method + target + version).
#: A longer line without a CRLF is rejected with a 414.
DEFAULT_MAX_REQUEST_LINE_BYTES = const(1024)

#: Default cap on the total header-section bytes. Headers over this are
#: rejected with a 431.
DEFAULT_MAX_HEADERS_BYTES = const(4096)

#: Default per-connection deadline.
DEFAULT_REQUEST_TIMEOUT_MS = const(10000)

#: Default in-flight connection cap.
DEFAULT_MAX_CONNECTIONS = const(4)

#: Default staging-window size for a streamed response.
DEFAULT_STREAM_BUFFER_SIZE = const(1024)

#: The streamed-body source's end-of-body sentinel (``-1``): "no more
#: body bytes ever", distinct from a ``0`` return ("none ready this tick").
SOURCE_EOF = const(-1)

#: HTTP/1.1 line terminator.
CRLF = b"\r\n"


# ---------------------------------------------------------------------------
# Server-facing exceptions
# ---------------------------------------------------------------------------


class ServerError(Exception):
    """Base class for chumicro-http-server failures."""


class ServerProtocolError(ServerError):
    """Inbound bytes don't conform to HTTP/1.1 (the connection returns 400)."""


class ServerLimitError(ServerError):
    """A sender-controlled allocation hit a documented cap.

    Carries :attr:`status_code` (the 413 / 414 / 431 the connection layer
    responds with) so the catch site need not hard-code it.
    """

    #: HTTP status the connection layer emits. Subclasses override.
    status_code = 400


class ServerOversizedError(ServerLimitError):
    """Request ``Content-Length`` exceeds ``max_body_bytes`` (413).

    :attr:`reported_length` is the length the client declared.
    """

    status_code = 413

    def __init__(self, message, *, reported_length):
        super().__init__(message)
        self.reported_length = reported_length


class ServerRequestLineTooLargeError(ServerLimitError):
    """Request line grew past ``max_request_line_bytes`` without a CRLF (414)."""

    status_code = 414


class ServerHeadersTooLargeError(ServerLimitError):
    """Header section grew past ``max_headers_bytes`` (431)."""

    status_code = 431


# ---------------------------------------------------------------------------
# Case-insensitive header dict
# ---------------------------------------------------------------------------


class CaseInsensitiveDict:
    """Header dict whose lookups fold to lowercase.

    Stores the original-cased name (callers see ``Content-Type``, not
    ``content-type``) keyed off the lowercased form. A header that arrives
    twice has its values joined with ``, `` per RFC 7230 §3.2.2.
    """

    def __init__(self):
        # noqa: CHU027 - same dict body as chumicro-requests _wire.py; per-consumer duplication kept intentionally
        # Lowercase key -> (original_name, value). ``_order`` tracks
        # insertion order (MicroPython/CircuitPython dicts don't preserve it).
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

    def add(self, name, value):  # noqa: CHU027 - same docstring as chumicro-requests _wire.add; per-consumer duplication kept intentionally
        """Append *value* to an existing header, joining with ``, ``.

        A new name behaves like :meth:`__setitem__`.
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


def parse_charset(content_type: str | None) -> str:  # noqa: CHU027 - same docstring as chumicro-requests _wire.parse_charset; per-consumer duplication kept intentionally
    """Extract the ``charset=...`` parameter from a Content-Type header.

    Falls back to ``"utf-8"`` when no charset is present or the header is
    missing.

    Args:
        content_type: Raw ``Content-Type`` header value, or ``None``.

    Returns:
        The detected charset name, or ``"utf-8"`` as the default.
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


#: Parser states where no further :meth:`RequestParser.feed` can progress.
#: Module-scoped so the per-chunk membership test reuses one tuple.
_PARSER_TERMINAL_STATES = (RequestParseState.DONE, RequestParseState.ERROR)


class RequestParser:
    """Streaming HTTP/1.1 request parser.

    Fed raw bytes via :meth:`feed`; the state advances as soon as enough
    bytes arrive. Callers check :attr:`state` to know whether to keep
    feeding (anything other than ``DONE`` / ``ERROR``) or stop. Chunked
    request bodies are not supported.
    """

    def __init__(
        self,
        *,
        max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES,
        max_request_line_bytes: int = DEFAULT_MAX_REQUEST_LINE_BYTES,
        max_headers_bytes: int = DEFAULT_MAX_HEADERS_BYTES,
        body_buffer: bytearray | None = None,
        body_buffer_view: memoryview | None = None,
    ) -> None:
        """Construct a one-shot parser.

        Args:
            max_body_bytes: Hard cap on body size; a bigger body raises
                :class:`ServerOversizedError` (413).
            max_request_line_bytes: Hard cap on the request-line length; a
                longer line without a CRLF raises
                :class:`ServerRequestLineTooLargeError` (414).
            max_headers_bytes: Hard cap on the total header-section bytes;
                crossing it raises :class:`ServerHeadersTooLargeError` (431).
            body_buffer: Optional caller-owned ``bytearray`` reused as a
                steady-state body buffer; ``None`` allocates a sized-to-fit
                buffer per body.
            body_buffer_view: Pre-cached ``memoryview(body_buffer)``; made
                for you when omitted.
        """
        self._max_body_bytes = max_body_bytes
        self._max_request_line_bytes = max_request_line_bytes
        self._max_headers_bytes = max_headers_bytes
        # Running total of header bytes consumed in HEADERS state, checked
        # with the unconsumed buffer so many small headers can't slip the cap.
        self._headers_bytes = 0
        self._buffer = bytearray()
        # Read cursor into ``_buffer``; ``_consume`` compacts the bytearray
        # only once at least half has been consumed.
        self._read_offset = 0
        self.state = RequestParseState.REQUEST_LINE
        self.method = ""
        self.target = ""
        self.http_version = ""
        self.headers = CaseInsensitiveDict()
        # Body buffer state: ``_body`` is where writes land, ``_body_view``
        # its cached memoryview, ``_body_capacity`` its current size.
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
    # Buffer helpers (read-cursor pattern, see ResponseParser)
    # ------------------------------------------------------------------

    def _live_len(self):
        return len(self._buffer) - self._read_offset

    def _live_find(self, target):
        position = self._buffer.find(target, self._read_offset)
        if position == -1:
            return -1
        return position - self._read_offset

    def _live_slice(self, start, end=None):
        absolute_start = self._read_offset + start
        if end is None:
            return self._buffer[absolute_start:]
        return self._buffer[absolute_start:absolute_start + end]

    def _consume(self, count):
        self._read_offset += count
        if self._read_offset > 0 and self._read_offset * 2 >= len(self._buffer):
            # Slice-assign-empty is an in-place memmove (no allocation).
            self._buffer[:self._read_offset] = b""
            self._read_offset = 0

    def _reset_buffer(self):
        self._buffer = bytearray()
        self._read_offset = 0

    # ------------------------------------------------------------------
    # Public observation
    # ------------------------------------------------------------------
    #
    # ``state`` / ``method`` / ``target`` / ``http_version`` / ``headers`` /
    # ``error`` are public attributes set during parsing; ``body`` needs a
    # computed view, so it stays a property.

    @property
    def body(self):
        """Body bytes received so far (final once :attr:`state` is ``DONE``)."""
        return bytes(self._body_view[:self._body_write_offset])

    # ------------------------------------------------------------------
    # Driving the parser
    # ------------------------------------------------------------------

    def feed(self, chunk):
        """Append *chunk* to the parser's buffer and advance the state.

        Raises:
            ServerProtocolError: The bytes don't conform to HTTP/1.1.
        """
        if self.state in _PARSER_TERMINAL_STATES:
            return
        if chunk:
            if self.state == RequestParseState.BODY:
                self._absorb_body_bytes(chunk)
            else:
                self._buffer.extend(chunk)
        self._advance()

    def feed_eof(self):
        """Signal that the peer closed.  Mid-headers is a protocol error."""
        if self.state in _PARSER_TERMINAL_STATES:
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
        crlf_index = self._live_find(CRLF)
        if crlf_index == -1:
            # No complete line yet: length check only, bounding the buffer a
            # no-CRLF dribble can grow. A line of exactly the cap still passes.
            if self._live_len() > self._max_request_line_bytes:
                self._fail(ServerRequestLineTooLargeError(
                    f"request line exceeds cap {self._max_request_line_bytes}",
                ))
                return True
            return False
        # Reject when the line itself exceeds the cap: without this, a line
        # whose CRLF lands in the over-cap chunk would make 414 soft.
        if crlf_index > self._max_request_line_bytes:
            self._fail(ServerRequestLineTooLargeError(
                f"request line exceeds cap {self._max_request_line_bytes}",
            ))
            return True
        line = self._live_slice(0, crlf_index)
        self._consume(crlf_index + 2)
        try:
            text = str(line, "ascii")
        # Catch ValueError, not UnicodeDecodeError: MicroPython and
        # CircuitPython lack that builtin (it subclasses ValueError on CPython).
        except ValueError as decode_error:  # pragma: no cover
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

    def _try_parse_headers(self):  # noqa: CHU027 - same parse loop as chumicro-requests _wire._try_parse_headers; per-consumer duplication kept intentionally
        # Section-total cap: consumed header bytes plus the unconsumed
        # buffer, bounding both a no-CRLF dribble and many small headers.
        if self._headers_bytes + self._live_len() > self._max_headers_bytes:
            self._fail(ServerHeadersTooLargeError(
                f"header section exceeds cap {self._max_headers_bytes}",
            ))
            return True
        crlf_index = self._live_find(CRLF)
        if crlf_index == -1:
            return False
        if crlf_index == 0:
            # Empty line: end of headers.
            self._headers_bytes += 2
            self._consume(2)
            self._enter_body_state()
            return True
        line = self._live_slice(0, crlf_index)
        self._headers_bytes += crlf_index + 2
        self._consume(crlf_index + 2)
        try:
            text = str(line, "ascii")
        # Catch ValueError, not UnicodeDecodeError: same cross-runtime
        # reason as the request-line parser above.
        except ValueError as decode_error:  # pragma: no cover
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
        if self.headers.get("Transfer-Encoding") is not None:
            # Chunked bodies are unsupported; framing one as zero-length
            # would let a smuggled body ride into the next request. Reject.
            self._fail(ServerProtocolError(
                "Transfer-Encoding request bodies are not supported",
            ))
            return
        content_length_str = self.headers.get("Content-Length")
        if content_length_str is None:
            # No Content-Length, no chunked: assume zero body.
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
            # 413 before any body allocation: the connection layer catches
            # ``ServerOversizedError`` and responds 413, not a generic 400.
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
        # Rebind to a sized buffer when the steady buffer can't hold this
        # request; a buffer that already fits touches no heap.
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
        # ``_body`` was sized to Content-Length in _enter_body_state, so
        # every write fits and slice-assign needs no grow fallback.
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
        self.error = error
        self.state = RequestParseState.ERROR


# ---------------------------------------------------------------------------
# Request-target helpers
# ---------------------------------------------------------------------------


def split_target(target: str) -> tuple[str, str]:
    """Split a request-target into ``(path, raw_query)``.

    *raw_query* is everything after the first ``?``, or ``""`` when there
    is none.
    """
    question_index = target.find("?")
    if question_index == -1:
        return target, ""
    return target[:question_index], target[question_index + 1:]


def parse_query(raw_query: str) -> "CaseInsensitiveDict":
    """Parse a ``foo=bar&baz=qux`` query string into a header-shaped dict.

    Keys fold to lowercase (so ``a=1&A=2`` merge into one entry) and
    percent-encoding is not decoded. Repeated keys join with ``, ``.
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


__all__ = [
    "CRLF",
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_MAX_HEADERS_BYTES",
    "DEFAULT_MAX_REQUEST_BODY_BYTES",
    "DEFAULT_MAX_REQUEST_LINE_BYTES",
    "DEFAULT_RECV_BUDGET_PER_TICK",
    "DEFAULT_REQUEST_TIMEOUT_MS",
    "DEFAULT_SEND_BUDGET_PER_TICK",
    "DEFAULT_STREAM_BUFFER_SIZE",
    "SOURCE_EOF",
    "CaseInsensitiveDict",
    "RequestParseState",
    "RequestParser",
    "ServerError",
    "ServerHeadersTooLargeError",
    "ServerLimitError",
    "ServerOversizedError",
    "ServerProtocolError",
    "ServerRequestLineTooLargeError",
    "parse_charset",
    "parse_query",
    "split_target",
]
