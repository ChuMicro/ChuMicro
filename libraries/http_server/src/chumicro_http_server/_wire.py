"""``chumicro_http_server._wire`` parses HTTP/1.1 requests from bytes its caller supplies.

It also holds the server's size limits and error types.
"""

try:
    from micropython import const
except ImportError:
    def const(value):
        return value


DEFAULT_RECV_BUDGET_PER_TICK = const(1024)

DEFAULT_SEND_BUDGET_PER_TICK = const(4096)

#: Bodies larger than this cap are rejected with 413.
DEFAULT_MAX_REQUEST_BODY_BYTES = const(16384)

#: A longer request line without a CRLF is rejected with 414.
DEFAULT_MAX_REQUEST_LINE_BYTES = const(1024)

#: Header sections larger than this are rejected with 431.
DEFAULT_MAX_HEADERS_BYTES = const(4096)

DEFAULT_REQUEST_TIMEOUT_MS = const(10000)

DEFAULT_MAX_CONNECTIONS = const(4)

DEFAULT_STREAM_BUFFER_SIZE = const(1024)

#: End-of-body sentinel (-1), distinct from a 0 return (none ready this tick).
SOURCE_EOF = const(-1)

CRLF = b"\r\n"


class ServerError(Exception):
    """``ServerError`` is the base class of the errors the request parser and response encoders raise."""


class ServerProtocolError(ServerError):
    """``ServerProtocolError`` reports request bytes that break HTTP/1.1.

    A request with a ``Transfer-Encoding`` header counts as a break.
    ``HttpServer`` closes a connection whose request raises it, with no
    response.  The response encoders also raise it for a reason phrase or
    header that holds CR, LF, or NUL, and ``HttpServer`` then sends a 500 in
    place of the route handler's response.
    """


class ServerLimitError(ServerError):
    """``ServerLimitError`` reports a request that passed one of the server's size limits.

    ``HttpServer`` answers with ``status_code`` and closes the connection.

    Attributes:
        status_code: HTTP status for the answer.  Each subclass sets its own.
    """

    status_code = 400


class ServerOversizedError(ServerLimitError):
    """``ServerOversizedError`` reports a request whose ``Content-Length`` exceeds the body limit.

    ``HttpServer`` answers 413.

    Attributes:
        reported_length: The ``Content-Length`` the client sent, in bytes.
    """

    status_code = 413

    def __init__(self, message, *, reported_length):
        super().__init__(message)
        self.reported_length = reported_length


class ServerRequestLineTooLargeError(ServerLimitError):
    """``ServerRequestLineTooLargeError`` reports a request line longer than ``max_request_line_bytes``.

    ``HttpServer`` answers 414.
    """

    status_code = 414


class ServerHeadersTooLargeError(ServerLimitError):
    """``ServerHeadersTooLargeError`` reports a header section longer than ``max_headers_bytes``.

    ``HttpServer`` answers 431.
    """

    status_code = 431


class CaseInsensitiveDict:
    """``CaseInsensitiveDict`` holds headers and query parameters, with lookups that ignore letter case.

    ``request.headers["content-type"]`` finds a ``Content-Type`` entry.  It
    supports ``[]`` lookup and assignment, ``in``, ``len``, iteration over
    names in the order they were first added, ``get``, ``items``, and ``add``.
    """

    def __init__(self):
        # noqa: CHU027 - same dict body as chumicro-requests _wire.py; per-consumer duplication kept intentionally
        # ``_order`` tracks insertion order; MicroPython/CircuitPython dicts don't.
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
        """Return the value for ``name`` in any letter case, or ``default``."""
        entry = self._entries.get(name.lower())
        if entry is None:
            return default
        return entry[1]

    def items(self):
        """Yield ``(original_name, value)`` pairs in insertion order."""
        for lower in self._order:
            yield self._entries[lower]

    def add(self, name, value):  # noqa: CHU027 - same docstring as chumicro-requests _wire.add; per-consumer duplication kept intentionally
        """Add ``value`` under ``name``, joined to any existing value with a comma and a space."""
        lower = name.lower()
        existing = self._entries.get(lower)
        if existing is None:
            self._order.append(lower)
            self._entries[lower] = (name, value)
            return
        original_name, current_value = existing
        joined = f"{current_value}, {value}"
        self._entries[lower] = (original_name, joined)


def parse_charset(content_type: str | None) -> str:  # noqa: CHU027 - same docstring as chumicro-requests _wire.parse_charset; per-consumer duplication kept intentionally
    """Return the ``charset`` parameter of a ``Content-Type`` header value.

    ``"text/plain; charset=iso-8859-1"`` gives ``"iso-8859-1"``.

    Args:
        content_type: Raw ``Content-Type`` header value, or ``None``.

    Returns:
        The charset name, or ``"utf-8"`` when the header is missing or names
            no charset.
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


class RequestParseState:
    """``RequestParseState`` names the values ``RequestParser.state`` takes.

    A request moves from ``REQUEST_LINE`` to ``HEADERS``, then to ``BODY``
    when a ``Content-Length`` body follows.  ``DONE`` means the whole request
    arrived.  ``ERROR`` means ``RequestParser.error`` holds the failure.
    """

    REQUEST_LINE = "request_line"
    HEADERS = "headers"
    BODY = "body"
    DONE = "done"
    ERROR = "error"


_PARSER_TERMINAL_STATES = (RequestParseState.DONE, RequestParseState.ERROR)


class RequestParser:
    """``RequestParser`` turns the bytes of one HTTP/1.1 request into a method, target,
    headers, and body as they arrive.

    ``feed`` takes each received chunk, and ``feed_eof`` records that the
    client closed the connection.  At ``RequestParseState.DONE`` the
    attributes hold the request.  At ``RequestParseState.ERROR``, ``error``
    holds the exception.  A request body must carry ``Content-Length``.  A
    ``Transfer-Encoding`` header, chunked included, fails the parser.

    Attributes:
        state: Current ``RequestParseState`` value.
        method: Request method, such as ``"GET"``.
        target: Raw request target, such as ``"/api?page=2"``.
        http_version: Version from the request line, such as ``"HTTP/1.1"``.
        headers: ``CaseInsensitiveDict`` of the request headers.
        error: The ``ServerError`` that stopped the parser, or ``None``.
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
        """Create a parser for one request.

        Args:
            max_body_bytes: Largest ``Content-Length`` accepted, in bytes.  A
                larger one fails the parser with ``ServerOversizedError``
                before any body is read.
            max_request_line_bytes: Longest request line, in bytes.  A longer
                one fails the parser with ``ServerRequestLineTooLargeError``.
            max_headers_bytes: Largest header section, in bytes.  A larger one
                fails the parser with ``ServerHeadersTooLargeError``.
            body_buffer: ``bytearray`` to reuse for bodies that fit in it, so
                successive parsers share one allocation, or ``None`` to
                allocate per body.
            body_buffer_view: ``memoryview(body_buffer)``, or ``None`` to
                create it.
        """
        self._max_body_bytes = max_body_bytes
        self._max_request_line_bytes = max_request_line_bytes
        self._max_headers_bytes = max_headers_bytes
        self._headers_bytes = 0
        self._buffer = bytearray()
        self._read_offset = 0
        self.state = RequestParseState.REQUEST_LINE
        self.method = ""
        self.target = ""
        self.http_version = ""
        self.headers = CaseInsensitiveDict()
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

    def _live_len(self):
        return len(self._buffer) - self._read_offset

    def _live_find(self, target):
        position = self._buffer.find(target, self._read_offset)
        if position == -1:
            return -1
        return position - self._read_offset

    def _live_slice(self, start, length=None):
        absolute_start = self._read_offset + start
        if length is None:
            return self._buffer[absolute_start:]
        return self._buffer[absolute_start:absolute_start + length]

    def _consume(self, count):
        self._read_offset += count
        if self._read_offset > 0 and self._read_offset * 2 >= len(self._buffer):
            # Slice-assign-empty is an in-place memmove (no allocation).
            self._buffer[:self._read_offset] = b""
            self._read_offset = 0

    def _reset_buffer(self):
        self._buffer = bytearray()
        self._read_offset = 0

    @property
    def body(self):
        """A copy of the body bytes received so far.

        The body is complete once ``state`` is ``RequestParseState.DONE``.
        """
        return bytes(self._body_view[:self._body_write_offset])

    def feed(self, chunk):
        """Parse ``chunk``, the next bytes received from the client, and advance ``state``.

        A request that breaks HTTP/1.1 or passes a size limit moves ``state``
        to ``RequestParseState.ERROR`` and stores the exception in ``error``.
        A call after ``DONE`` or ``ERROR`` does nothing.

        Raises:
            ServerProtocolError: The request line or a header line holds
                non-ASCII bytes.  The parser also stores it in ``error``.
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
        """Record that the client closed the connection.

        A close before ``DONE`` fails the parser with ``ServerProtocolError``.
        """
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
            return  # BODY handled in feed(); DONE / ERROR are terminal

    def _try_parse_request_line(self):
        crlf_index = self._live_find(CRLF)
        if crlf_index == -1:
            # No CRLF yet: bound the buffer so a no-CRLF stream can't grow unbounded.
            if self._live_len() > self._max_request_line_bytes:
                self._fail(ServerRequestLineTooLargeError(
                    f"request line exceeds cap {self._max_request_line_bytes}",
                ))
                return True
            return False
        # Also reject when the found line exceeds the cap, or 414 goes soft.
        if crlf_index > self._max_request_line_bytes:
            self._fail(ServerRequestLineTooLargeError(
                f"request line exceeds cap {self._max_request_line_bytes}",
            ))
            return True
        line = self._live_slice(0, crlf_index)
        self._consume(crlf_index + 2)
        try:
            text = str(line, "ascii")
        # Catch ValueError, not UnicodeDecodeError: MicroPython/CircuitPython lack that builtin.
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
        # Cap consumed plus unconsumed bytes, bounding a no-CRLF stream and many small headers.
        if self._headers_bytes + self._live_len() > self._max_headers_bytes:
            self._fail(ServerHeadersTooLargeError(
                f"header section exceeds cap {self._max_headers_bytes}",
            ))
            return True
        crlf_index = self._live_find(CRLF)
        if crlf_index == -1:
            return False
        if crlf_index == 0:
            # Blank line ends the header section.
            self._headers_bytes += 2
            self._consume(2)
            self._enter_body_state()
            return True
        line = self._live_slice(0, crlf_index)
        self._headers_bytes += crlf_index + 2
        self._consume(crlf_index + 2)
        try:
            text = str(line, "ascii")
        # Catch ValueError, not UnicodeDecodeError (same cross-runtime reason as above).
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
            # Reject chunked: framing it as zero-length would allow request smuggling.
            self._fail(ServerProtocolError(
                "Transfer-Encoding request bodies are not supported",
            ))
            return
        content_length_str = self.headers.get("Content-Length")
        if content_length_str is None:
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
            # Raise before allocating any body, so the layer returns 413 not a generic 400.
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
        # Grow the body buffer only when the steady buffer can't hold this request.
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
        # _body was sized to Content-Length, so every write fits with no grow path.
        if self._body_remaining == 0:
            return  # Body already complete; drop extra bytes the client sent.
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


def split_target(target: str) -> tuple[str, str]:
    """Split a request target into ``(path, raw_query)`` at the first ``?``.

    ``"/items?page=2"`` gives ``("/items", "page=2")``.  A target without
    ``?`` gives ``(target, "")``.
    """
    question_index = target.find("?")
    if question_index == -1:
        return target, ""
    return target[:question_index], target[question_index + 1:]


def parse_query(raw_query: str) -> "CaseInsensitiveDict":
    """Parse a query string such as ``"page=2&sort=name"`` into a ``CaseInsensitiveDict``.

    A repeated name joins its values with a comma and a space.  A name with
    no ``=`` maps to ``""``.  Percent-escapes such as ``%20`` stay as
    received.
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
