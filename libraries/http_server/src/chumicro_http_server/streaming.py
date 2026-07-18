"""Streamed response bodies for chumicro-http-server (opt-in submodule).

The entry points are :class:`StreamingResponse` and :func:`build_streaming_response`.
"""

import errno

from chumicro_http_server._wire import (
    CRLF,
    DEFAULT_STREAM_BUFFER_SIZE,
    SOURCE_EOF,
    CaseInsensitiveDict,
    ServerError,
)

# server.py lazy-imports this module (never the reverse at load time), so
# by the time this runs server.py is fully loaded and these resolve.
from chumicro_http_server.server import (
    _ENCODED_500_ERROR,
    _REASONS,
    _ConnState,
    _merge_headers,
    _reject_control_chars,
)

__all__ = [
    "DEFAULT_STREAM_BUFFER_SIZE",
    "SOURCE_EOF",
    "StreamingResponse",
    "build_streaming_response",
    "encode_streaming_headers",
]

# Chunked-body terminator: zero-length chunk plus closing CRLF.
_CHUNK_TERMINATOR = b"0\r\n\r\n"
_CHUNK_TERMINATOR_VIEW = memoryview(_CHUNK_TERMINATOR)

# Lowercase hex for the chunk-size line (RFC 7230 §4.1).
_HEX_DIGITS = b"0123456789abcdef"


class _StreamError(ServerError):
    """Streamed-send failure that breaks framing mid-body."""


class _StreamSourceError(_StreamError):
    """The byte source violated its contract mid-transfer."""


class _StreamHandlerError(_StreamError):
    """The byte source raised mid-transfer (original on ``__cause__``)."""


def _hex_len(value):
    length = 1
    while value >= 16:
        value >>= 4
        length += 1
    return length


def _write_chunk_header(buffer, end, size):
    # Write ``<hex-size>\r\n`` backwards into the buffer ending at *end*, with
    # no per-chunk alloc; returns the header length (chunk starts at end - it).
    buffer[end - 1] = 0x0A  # \n
    buffer[end - 2] = 0x0D  # \r
    position = end - 2
    value = size
    while True:
        position -= 1
        buffer[position] = _HEX_DIGITS[value & 0xF]
        value >>= 4
        if value == 0:
            break
    return end - position


class _StreamState:
    def __init__(self, source, content_length, buffer):
        self._source = source
        self._content_length = content_length
        self._chunked = content_length is None
        self._buffer = buffer
        self._view = memoryview(buffer)
        total = len(buffer)
        if self._chunked:
            # Reserve a head for the chunk-size line and a 2-byte tail CRLF, so a framed chunk is contiguous.
            self._header_reserve = _hex_len(total) + 2
            self._fill_capacity = total - self._header_reserve - 2
            if self._fill_capacity < 1:
                raise ValueError(
                    f"stream buffer of {total} B too small to frame a "
                    "chunk; use a larger stream_buffer_size",
                )
            self._fill_view = self._view[
                self._header_reserve:self._header_reserve + self._fill_capacity
            ]
        else:
            self._header_reserve = 0
            self._fill_capacity = total
            self._fill_view = self._view
        self._body_sent = 0
        self._eof = False
        self.out_view = self._view
        self.out_pos = 0
        self.out_end = 0

    @property
    def pending(self):
        return self.out_pos < self.out_end

    @property
    def finished(self):
        return self._eof and self.out_pos >= self.out_end

    @property
    def body_bytes_sent(self):
        return self._body_sent

    def advance_sent(self, count):
        self.out_pos += count

    def pull(self):
        """Poll the source once and frame the result.

        Returns:
            ``True`` if it framed data or handled EOF, ``False`` if the source is dry this tick.
        """
        count = self._source(self._fill_view)
        if count == SOURCE_EOF:
            self._on_eof()
            return True
        if count == 0:
            return False
        if count < 0 or count > self._fill_capacity:
            raise _StreamSourceError(
                f"streaming source returned {count}; expected "
                f"0..{self._fill_capacity} or SOURCE_EOF ({SOURCE_EOF})",
            )
        self._frame_data(count)
        return True

    def _frame_data(self, count):
        if self._chunked:
            reserve = self._header_reserve
            header_len = _write_chunk_header(self._buffer, reserve, count)
            body_end = reserve + count
            self._buffer[body_end] = 0x0D  # \r
            self._buffer[body_end + 1] = 0x0A  # \n
            self.out_view = self._view
            self.out_pos = reserve - header_len
            self.out_end = body_end + 2
        else:
            remaining = self._content_length - self._body_sent
            if count > remaining:
                raise _StreamSourceError(
                    "streaming source produced more than the declared "
                    f"Content-Length {self._content_length}",
                )
            self.out_view = self._view
            self.out_pos = 0
            self.out_end = count
        self._body_sent += count

    def _on_eof(self):
        self._eof = True
        if self._chunked:
            self.out_view = _CHUNK_TERMINATOR_VIEW
            self.out_pos = 0
            self.out_end = len(_CHUNK_TERMINATOR)
        elif self._body_sent != self._content_length:
            raise _StreamSourceError(
                f"streaming source signalled EOF after {self._body_sent} "
                f"bytes but declared Content-Length {self._content_length}",
            )


class StreamingResponse:
    """A response whose body a byte source produces incrementally."""

    def __init__(
        self,
        *,
        status_code: int,
        reason: str,
        headers: object,
        source: object,
        content_length: int | None,
    ) -> None:
        self.status_code = status_code
        self.reason = reason
        self.headers = headers
        self.source = source
        self.content_length = content_length

    def __repr__(self) -> str:
        framing = (
            "chunked" if self.content_length is None
            else f"content-length={self.content_length}"
        )
        return f"StreamingResponse(status_code={self.status_code}, {framing})"


def build_streaming_response(
    status: int = 200,
    *,
    source: object,
    content_length: int | None = None,
    headers: object | None = None,
) -> StreamingResponse:
    """Build a :class:`StreamingResponse` served from a byte *source*.

    Args:
        status: HTTP status code (default ``200``).
        source: Fill callable ``source(buffer) -> int``; bytes written, 0 if none ready, or SOURCE_EOF.
        content_length: Total to frame as ``Content-Length``; ``None`` (default) frames chunked.
        headers: Optional extra headers; do not set Content-Length / Transfer-Encoding / Connection.

    Returns:
        A :class:`StreamingResponse` for the handler to return.
    """
    merged_headers = CaseInsensitiveDict()
    _merge_headers(merged_headers, headers)
    return StreamingResponse(
        status_code=status,
        reason=_REASONS.get(status, "Unknown"),
        headers=merged_headers,
        source=source,
        content_length=content_length,
    )


def encode_streaming_headers(response: StreamingResponse) -> bytes:
    """Serialize a :class:`StreamingResponse`'s header block to wire bytes.

    Raises:
        ServerProtocolError: The reason phrase or a header carries a CR, LF, or NUL.
    """
    _reject_control_chars("reason", str(response.reason))
    headers = CaseInsensitiveDict()
    if response.content_length is not None:
        headers["Content-Length"] = str(response.content_length)
    else:
        headers["Transfer-Encoding"] = "chunked"
    headers["Connection"] = "close"
    _merge_headers(headers, response.headers)
    parts = [
        f"HTTP/1.1 {response.status_code} {response.reason}\r\n".encode("ascii"),
    ]
    for name, value in headers.items():
        _reject_control_chars("header name", str(name))
        _reject_control_chars("header value", str(value))
        parts.append(f"{name}: {value}\r\n".encode("ascii"))
    parts.append(CRLF)
    return b"".join(parts)


def stage_streaming_response(conn, response):
    """Encode *response*'s headers onto *conn* and arm the source drain."""
    try:
        header_bytes = encode_streaming_headers(response)
    except Exception:  # noqa: BLE001 - unencodable headers, pre-body: a 500, not a crash
        conn._response_bytes = _ENCODED_500_ERROR
        conn._response_view = memoryview(conn._response_bytes)
        conn._response_offset = 0
        conn.state = _ConnState.WANT_SEND_HEADERS
        return
    if conn._stream_buffer is None:
        conn._stream_buffer = bytearray(conn._stream_buffer_size)
    conn._stream = _StreamState(
        response.source, response.content_length, conn._stream_buffer,
    )
    conn._response_bytes = header_bytes
    conn._response_view = memoryview(header_bytes)
    conn._response_offset = 0
    conn.state = _ConnState.WANT_SEND_HEADERS


def drive_stream_body(conn):
    """Drain *conn*'s byte source to its socket, framed, up to ``send_budget`` bytes this tick."""
    stream = conn._stream
    budget = conn._send_budget
    consumed = 0
    while consumed < budget:
        if stream.pending:
            start = stream.out_pos
            room = budget - consumed
            available = stream.out_end - start
            stop = start + (available if available <= room else room)
            chunk = stream.out_view[start:stop]
            try:
                sent = conn._socket.send(chunk)
            except OSError as socket_error:
                if socket_error.errno == errno.EAGAIN:
                    return
                raise
            if sent <= 0:  # pragma: no cover - non-blocking-EAGAIN backpressure path
                return
            stream.advance_sent(sent)
            consumed += sent
            continue
        if stream.finished:
            conn.state = _ConnState.DONE
            return
        try:
            progressed = stream.pull()
        except ServerError:
            # Contract violation or length mismatch; let the fail-and-close handler take it.
            raise
        except Exception as source_error:  # noqa: BLE001 - handler source raised mid-body
            # Bytes already on the wire; route through the fail-and-close path.
            raise _StreamHandlerError(
                f"streaming source raised mid-body: {source_error!r}",
            ) from source_error
        if not progressed:
            return  # source dry this tick; retry later
