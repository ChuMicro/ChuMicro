import binascii
import hashlib
import os
import struct

try:
    from micropython import const
except ImportError:
    def const(value):
        return value


_ZERO2 = b"\x00\x00"
_ZERO8 = b"\x00\x00\x00\x00\x00\x00\x00\x00"


def _append_packed_h(buffer: bytearray, value: int) -> None:
    buffer.extend(_ZERO2)
    struct.pack_into("!H", buffer, len(buffer) - 2, value)


def _append_packed_q(buffer: bytearray, value: int) -> None:
    buffer.extend(_ZERO8)
    struct.pack_into("!Q", buffer, len(buffer) - 8, value)


def _sha1_digest(data: bytes) -> bytes:
    # CircuitPython lacks hashlib.sha1 but has hashlib.new("sha1", ...).
    hasher_factory = getattr(hashlib, "sha1", None)
    if hasher_factory is not None:
        return hasher_factory(data).digest()
    return hashlib.new("sha1", data).digest()


class WebSocketError(Exception):
    """Base class for every chumicro-websockets failure."""


class WebSocketProtocolError(WebSocketError):
    """Peer sent bytes that RFC 6455 requires closing the connection on."""


class WebSocketHandshakeError(WebSocketError):
    """The opening handshake failed (bad status, headers, or HTTP framing)."""


class WebSocketURLError(WebSocketError):
    """URL doesn't parse as a supported ``ws://`` / ``wss://`` URL."""


class WebSocketTimeoutError(WebSocketError):
    """A per-phase timeout elapsed (handshake, close, or pong-after-ping)."""


class WebSocketBackpressureError(WebSocketError):
    """The TX queue overflowed before the runner could drain it."""


class WebSocketStateError(WebSocketError):
    """Caller invoked an operation that requires a different session state."""


#: RFC 6455 §1.3 magic GUID concatenated with the nonce to derive the accept key.
WS_MAGIC_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

#: RFC 6455 §4.1: required version token for the opening handshake.
WS_VERSION = "13"

CRLF = b"\r\n"

CRLF_CRLF = b"\r\n\r\n"

#: Default per-tick recv cap; small enough to keep tick latency LED-friendly.
DEFAULT_RECV_BUDGET_PER_TICK = const(1024)

DEFAULT_SEND_BUDGET_PER_TICK = const(1024)

#: Default inbound message cap; 16 KB leaves headroom on a 256 KB-RAM board.
DEFAULT_MAX_MESSAGE_BYTES = const(16384)

DEFAULT_MAX_TX_QUEUE_SIZE = const(8)

#: Default next_message queue bound; full drops the oldest message, not the newest.
DEFAULT_MAX_INBOUND_QUEUE_SIZE = const(16)

#: Steady-state :class:`FrameParser` payload buffer; covers short frames without allocating.
DEFAULT_PAYLOAD_BUFFER_SIZE = const(256)

DEFAULT_HANDSHAKE_TIMEOUT_MS = const(10000)

DEFAULT_CLOSE_TIMEOUT_MS = const(5000)

DEFAULT_PONG_TIMEOUT_MS = const(30000)

#: RFC 6455 §5.5: control payloads MUST be <=125 bytes.
MAX_CONTROL_PAYLOAD_BYTES = const(125)

# Opcodes: RFC 6455 §5.2.
OPCODE_CONTINUATION = const(0x0)
OPCODE_TEXT = const(0x1)
OPCODE_BINARY = const(0x2)
OPCODE_CLOSE = const(0x8)
OPCODE_PING = const(0x9)
OPCODE_PONG = const(0xA)

#: Data (non-control) opcodes, RFC 6455 §5.6.
DATA_OPCODES = frozenset({OPCODE_CONTINUATION, OPCODE_TEXT, OPCODE_BINARY})

#: Control-frame opcodes, RFC 6455 §5.5 (FIN=1, payload <= 125, may interleave).
CONTROL_OPCODES = frozenset({OPCODE_CLOSE, OPCODE_PING, OPCODE_PONG})

# Close codes: RFC 6455 §7.4.1 / §7.4.2.
CLOSE_NORMAL = const(1000)
CLOSE_GOING_AWAY = const(1001)
CLOSE_PROTOCOL_ERROR = const(1002)
CLOSE_UNSUPPORTED_DATA = const(1003)
CLOSE_NO_STATUS_RCVD = const(1005)  # reserved; never sent on the wire
CLOSE_ABNORMAL = const(1006)        # reserved; never sent on the wire
CLOSE_BAD_DATA = const(1007)
CLOSE_POLICY_VIOLATION = const(1008)
CLOSE_TOO_BIG = const(1009)
CLOSE_MISSING_EXTN = const(1010)
CLOSE_INTERNAL_ERROR = const(1011)
CLOSE_TLS_HANDSHAKE = const(1015)   # reserved; never sent on the wire

#: Close codes RFC 6455 §7.4.1 forbids on the wire; a peer sending one is a protocol error.
RESERVED_CLOSE_CODES = frozenset({
    CLOSE_NO_STATUS_RCVD,
    CLOSE_ABNORMAL,
    CLOSE_TLS_HANDSHAKE,
})


class WebSocketState:
    """Lifecycle states for a websocket session."""

    CONNECTING = "connecting"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class CaseInsensitiveDict:
    """Header dict whose lookups fold to lowercase."""

    def __init__(self):
        self._entries = {}
        # MicroPython/CircuitPython dicts don't preserve insertion order; _order drives items().
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


def parse_ws_url(url: str) -> tuple[str, str, int, str]:
    """Split a ``ws://`` or ``wss://`` *url* into ``(scheme, host, port, path)``.

    Raises:
        WebSocketURLError: Bad scheme, missing host, or out-of-range port.
    """
    if not isinstance(url, str):
        raise WebSocketURLError(
            f"url must be str, got {type(url).__name__}",
        )
    if url.startswith("ws://"):
        scheme = "ws"
        rest = url[5:]
        default_port = 80
    elif url.startswith("wss://"):
        scheme = "wss"
        rest = url[6:]
        default_port = 443
    else:
        raise WebSocketURLError(
            f"url must start with ws:// or wss://, got {url!r}",
        )
    if not rest:
        raise WebSocketURLError(f"url is missing host: {url!r}")

    slash_index = rest.find("/")
    if slash_index == -1:
        host_and_port = rest
        path = "/"
    else:
        host_and_port = rest[:slash_index]
        path = rest[slash_index:]

    if not host_and_port:
        raise WebSocketURLError(f"url is missing host: {url!r}")

    colon_index = host_and_port.find(":")
    if colon_index == -1:
        host = host_and_port
        port = default_port
    else:
        host = host_and_port[:colon_index]
        port_str = host_and_port[colon_index + 1:]
        if not host:
            raise WebSocketURLError(f"url is missing host: {url!r}")
        try:
            port = int(port_str)
        except ValueError as parse_error:
            raise WebSocketURLError(
                f"url has non-integer port {port_str!r}: {url!r}",
            ) from parse_error
        if port <= 0 or port > 65535:
            raise WebSocketURLError(
                f"url port {port} out of range 1-65535: {url!r}",
            )
    return scheme, host, port, path


def make_websocket_key() -> str:
    """Generate a fresh ``Sec-WebSocket-Key`` (16 random bytes, base64 ASCII) per RFC 6455 §4.1."""
    nonce = os.urandom(16)
    encoded = binascii.b2a_base64(nonce)
    # b2a_base64 appends a trailing newline byte.
    return encoded.rstrip(b"\n").rstrip(b"\r").decode("ascii")


def derive_accept_key(client_key: str) -> str:
    """Compute ``Sec-WebSocket-Accept`` from the client's nonce.

    Args:
        client_key: Verbatim base64 nonce; do not decode it first.
    """
    digest = _sha1_digest((client_key + WS_MAGIC_GUID).encode("ascii"))
    encoded = binascii.b2a_base64(digest)
    return encoded.rstrip(b"\n").rstrip(b"\r").decode("ascii")


def _merge_extra_headers(merged: "CaseInsensitiveDict", extra_headers) -> None:
    if extra_headers is None:
        return
    iterable = extra_headers.items() if hasattr(extra_headers, "items") else extra_headers
    for header_name, header_value in iterable:
        merged[header_name] = header_value


def encode_client_handshake(
    host: str,
    port: int,
    path: str,
    key: str,
    *,
    extra_headers: object | None = None,
) -> bytes:
    """Encode the client's opening-handshake HTTP/1.1 request.

    Args:
        host: Target host for the ``Host`` header.
        port: Target port; appended to ``Host`` only when non-default (80/443).
        path: Request path, including any query string.
        key: ``Sec-WebSocket-Key`` nonce.
        extra_headers: Caller headers merged before the mandatory upgrade headers.
    """
    is_default_port = port in (80, 443)
    host_value = host if is_default_port else f"{host}:{port}"

    merged = CaseInsensitiveDict()
    _merge_extra_headers(merged, extra_headers)
    # Mandatory upgrade headers applied last so callers can't override them.
    merged["Host"] = host_value
    merged["Upgrade"] = "websocket"
    merged["Connection"] = "Upgrade"
    merged["Sec-WebSocket-Key"] = key
    merged["Sec-WebSocket-Version"] = WS_VERSION

    parts = [f"GET {path} HTTP/1.1\r\n".encode("ascii")]
    for header_name, header_value in merged.items():
        parts.append(f"{header_name}: {header_value}\r\n".encode("ascii"))
    parts.append(CRLF)
    return b"".join(parts)


def encode_server_handshake_response(
    client_key: str,
    *,
    extra_headers: object | None = None,
) -> bytes:
    """Encode the server's ``101 Switching Protocols`` response.

    Args:
        client_key: Verbatim ``Sec-WebSocket-Key`` from the request.
        extra_headers: Caller headers merged before the mandatory upgrade headers.
    """
    accept_token = derive_accept_key(client_key)

    merged = CaseInsensitiveDict()
    _merge_extra_headers(merged, extra_headers)
    merged["Upgrade"] = "websocket"
    merged["Connection"] = "Upgrade"
    merged["Sec-WebSocket-Accept"] = accept_token

    parts = [b"HTTP/1.1 101 Switching Protocols\r\n"]
    for header_name, header_value in merged.items():
        parts.append(f"{header_name}: {header_value}\r\n".encode("ascii"))
    parts.append(CRLF)
    return b"".join(parts)


def encode_server_rejection(
    status_code: int,
    reason_phrase: str,
    *,
    body: bytes | None = None,
    content_type: str = "text/plain; charset=utf-8",
) -> bytes:
    """Encode an HTTP/1.1 error response for a rejected upgrade.

    Args:
        status_code: HTTP status code.
        reason_phrase: HTTP reason phrase.
        body: Optional response body; sets ``Content-Length`` automatically.
        content_type: ``Content-Type`` used when *body* is set.
    """
    parts = [f"HTTP/1.1 {status_code} {reason_phrase}\r\n".encode("ascii")]
    parts.append(b"Connection: close\r\n")
    if body is not None:
        parts.append(f"Content-Length: {len(body)}\r\n".encode("ascii"))
        parts.append(f"Content-Type: {content_type}\r\n".encode("ascii"))
    parts.append(CRLF)
    if body is not None:
        parts.append(body)
    return b"".join(parts)


class HandshakeParseState:
    """Streaming-handshake parser states."""

    REQUEST_LINE = "request_line"
    STATUS_LINE = "status_line"
    HEADERS = "headers"
    DONE = "done"
    ERROR = "error"


class _HandshakeLineParser:
    _initial_state: str = ""

    def __init__(self, *, max_header_bytes: int = 8192):
        self._max_header_bytes = max_header_bytes
        self._buffer = bytearray()
        # Read cursor into _buffer; slicing off consumed bytes would fragment the heap.
        self._read_offset = 0
        self.state = self._initial_state
        self.http_version = ""
        self.headers = CaseInsensitiveDict()
        self.error = None
        self.leftover = b""


    def feed(self, chunk: bytes) -> None:
        """Consume *chunk* bytes and advance state if possible.

        Raises:
            WebSocketHandshakeError: Overflow, malformed first line, or validation failure.
        """
        if self.state in (HandshakeParseState.DONE, HandshakeParseState.ERROR):
            return
        self._buffer.extend(chunk)
        # Cap on unconsumed bytes: len(_buffer) would over-count not-yet-compacted bytes.
        if self._live_len() > self._max_header_bytes:
            raise self._fail(
                f"handshake exceeded max_header_bytes={self._max_header_bytes}",
            )

        while True:
            terminator_index = self._live_find(CRLF)
            if terminator_index == -1:
                return
            line = bytes(self._live_slice(0, terminator_index))
            self._consume(terminator_index + 2)

            if self.state == HandshakeParseState.HEADERS:
                if not line:
                    self._finalize()
                    return
                self._parse_header_line(line)
            else:
                self._parse_first_line(line)

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
        # Compact past halfway: slice-assign-empty is an in-place memmove, no allocation.
        if self._read_offset > 0 and self._read_offset * 2 >= len(self._buffer):
            self._buffer[:self._read_offset] = b""
            self._read_offset = 0

    def _parse_header_line(self, line: bytes) -> None:
        # MicroPython/CircuitPython decode as UTF-8 regardless of codec; catch UnicodeError.
        try:
            decoded = line.decode("iso-8859-1")
        except UnicodeError as decode_error:
            raise self._fail(
                f"undecodable bytes in header line: {decode_error}",
            ) from decode_error
        colon_index = decoded.find(":")
        if colon_index == -1:
            raise self._fail(f"header line missing colon: {decoded!r}")
        header_name = decoded[:colon_index].strip()
        header_value = decoded[colon_index + 1:].strip()
        if not header_name:
            raise self._fail(f"empty header name in {decoded!r}")
        self.headers[header_name] = header_value

    def _validate_upgrade_headers(self, role_label: str) -> None:
        upgrade = self.headers.get("Upgrade", "").lower()
        if "websocket" not in upgrade:
            raise self._fail(
                f"{role_label} missing 'Upgrade: websocket' (got {upgrade!r})",
            )
        connection = self.headers.get("Connection", "").lower()
        connection_tokens = {token.strip() for token in connection.split(",")}
        if "upgrade" not in connection_tokens:
            raise self._fail(
                f"{role_label} missing 'Connection: Upgrade' (got {connection!r})",
            )

    def _commit_done(self) -> None:
        self.leftover = bytes(self._live_slice(0))
        self._buffer = bytearray()
        self._read_offset = 0
        self.state = HandshakeParseState.DONE

    def _fail(self, message: str) -> WebSocketHandshakeError:
        self.error = message
        self.state = HandshakeParseState.ERROR
        return WebSocketHandshakeError(message)

    def _parse_first_line(self, line: bytes) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def _finalize(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class HandshakeResponseParser(_HandshakeLineParser):
    """Streaming parser for the server's HTTP/1.1 ``101`` response."""

    _initial_state = HandshakeParseState.STATUS_LINE

    def __init__(self, expected_accept: str, *, max_header_bytes: int = 8192):
        super().__init__(max_header_bytes=max_header_bytes)
        self._expected_accept = expected_accept
        self.status_code = None
        self.reason = ""

    def _parse_first_line(self, line: bytes) -> None:
        try:
            decoded = line.decode("ascii")
        except UnicodeError as decode_error:
            raise self._fail(
                f"non-ASCII bytes in status line: {decode_error}",
            ) from decode_error
        # "HTTP/1.1 101 Switching Protocols": split on first two spaces.
        parts = decoded.split(" ", 2)
        if len(parts) < 2:
            raise self._fail(f"malformed status line: {decoded!r}")
        self.http_version = parts[0]
        try:
            self.status_code = int(parts[1])
        except ValueError as parse_error:
            raise self._fail(
                f"non-integer status code: {decoded!r}",
            ) from parse_error
        self.reason = parts[2] if len(parts) == 3 else ""
        if self.status_code != 101:
            raise self._fail(
                f"server did not switch protocols: {self.status_code} "
                f"{self.reason}",
            )
        self.state = HandshakeParseState.HEADERS

    def _finalize(self) -> None:
        self._validate_upgrade_headers("server response")
        accept = self.headers.get("Sec-WebSocket-Accept", "")
        if accept != self._expected_accept:
            raise self._fail(
                f"Sec-WebSocket-Accept mismatch: expected "
                f"{self._expected_accept!r}, got {accept!r}",
            )
        self._commit_done()


class HandshakeRequestParser(_HandshakeLineParser):
    """Streaming parser for the client's HTTP/1.1 upgrade request."""

    _initial_state = HandshakeParseState.REQUEST_LINE

    def __init__(self, *, max_header_bytes: int = 8192):
        super().__init__(max_header_bytes=max_header_bytes)
        self.method = ""
        self.path = ""

    @property
    def client_key(self):
        """Verbatim ``Sec-WebSocket-Key`` once headers parse, else ``""``."""
        return self.headers.get("Sec-WebSocket-Key", "")

    def _parse_first_line(self, line: bytes) -> None:
        try:
            decoded = line.decode("ascii")
        except UnicodeError as decode_error:
            raise self._fail(
                f"non-ASCII bytes in request line: {decode_error}",
            ) from decode_error
        parts = decoded.split(" ")
        if len(parts) != 3:
            raise self._fail(f"malformed request line: {decoded!r}")
        self.method = parts[0]
        self.path = parts[1]
        self.http_version = parts[2]
        if self.method != "GET":
            raise self._fail(f"method must be GET, got {self.method!r}")
        if not self.http_version.startswith("HTTP/1."):
            raise self._fail(
                f"unsupported HTTP version {self.http_version!r}; "
                f"must be HTTP/1.1+",
            )
        self.state = HandshakeParseState.HEADERS

    def _finalize(self) -> None:
        self._validate_upgrade_headers("client request")
        version = self.headers.get("Sec-WebSocket-Version", "")
        if version != WS_VERSION:
            raise self._fail(
                f"unsupported Sec-WebSocket-Version {version!r}; "
                f"must be {WS_VERSION!r}",
            )
        key = self.headers.get("Sec-WebSocket-Key", "")
        if not key:
            raise self._fail("client request missing Sec-WebSocket-Key")
        try:
            decoded_key = binascii.a2b_base64(key.encode("ascii"))
        # binascii.Error subclasses ValueError on CPython; MicroPython raises ValueError.
        except ValueError as decode_error:
            raise self._fail(
                f"Sec-WebSocket-Key is not valid base64: {decode_error}",
            ) from decode_error
        if len(decoded_key) != 16:
            raise self._fail(
                f"Sec-WebSocket-Key must decode to 16 bytes, got "
                f"{len(decoded_key)}",
            )
        self._commit_done()


class FrameParseState:
    """Streaming binary-frame parser states."""

    READING_HEADER = "reading_header"
    READING_LEN16 = "reading_len16"
    READING_LEN64 = "reading_len64"
    READING_MASK = "reading_mask"
    READING_PAYLOAD = "reading_payload"
    DRAINING_PAYLOAD = "draining_payload"
    FRAME_READY = "frame_ready"
    ERROR = "error"


class FrameParser:
    """Streaming RFC 6455 §5 binary-frame parser, one frame at a time.

    Args:
        max_payload_bytes: Per-frame payload cap; bounds heap, not connection lifetime.
        payload_buffer_size: Steady-state payload buffer size reused across frames.
    """

    def __init__(
        self,
        *,
        max_payload_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        payload_buffer_size: int = DEFAULT_PAYLOAD_BUFFER_SIZE,
    ):
        self._max_payload_bytes = max_payload_bytes
        self.state = FrameParseState.READING_HEADER
        # 8-byte scratch reused across header/length/mask fields; _header_len is the cursor.
        self._header_scratch = bytearray(8)
        self._header_view = memoryview(self._header_scratch)
        self._header_len = 0
        self.fin = False
        self.rsv = 0
        self.opcode = 0
        self.had_mask = False
        self.reported_length = 0
        self._mask_key = b""
        # memoryview over the steady buffer so per-write indexing doesn't re-create it.
        self._payload_buffer = bytearray(payload_buffer_size)
        self._payload_buffer_view = memoryview(self._payload_buffer)
        self._payload_capacity = payload_buffer_size
        self._payload = self._payload_buffer
        self._payload_view = self._payload_buffer_view
        self._payload_write_offset = 0
        # Tier-3 drain state: oversized flips true when declared length exceeds the cap.
        self.oversized = False
        self._drain_remaining = 0
        self.error = None

    @property
    def payload(self):
        """Unmasked payload of the just-completed frame as ``bytes``."""
        return bytes(self._payload_view[:self._payload_write_offset])

    def reset(self) -> None:
        """Return to ``READING_HEADER`` for the next frame."""
        self.state = FrameParseState.READING_HEADER
        self._header_len = 0
        self.fin = False
        self.rsv = 0
        self.opcode = 0
        self.had_mask = False
        self.reported_length = 0
        self._mask_key = b""
        self._payload = self._payload_buffer
        self._payload_view = self._payload_buffer_view
        self._payload_write_offset = 0
        self.oversized = False
        self._drain_remaining = 0

    def feed(self, chunk: bytes, start: int = 0) -> int:
        """Consume bytes from *chunk* starting at *start*; return the count used.

        Raises:
            WebSocketProtocolError: Reserved opcode, or control frame with payload > 125 or FIN=0.
        """
        consumed = 0
        effective_length = len(chunk) - start
        # Bind a memoryview once so per-state slices are zero-copy.
        chunk_view = chunk if isinstance(chunk, memoryview) else memoryview(chunk)
        while consumed < effective_length and self.state not in (
            FrameParseState.FRAME_READY,
            FrameParseState.ERROR,
        ):
            remaining = effective_length - consumed
            cursor = start + consumed
            state = self.state
            if state == FrameParseState.READING_PAYLOAD:
                payload = self._payload
                write_offset = self._payload_write_offset
                need = self.reported_length - write_offset
                take = need if need <= remaining else remaining
                if self.had_mask:
                    mask_key = self._mask_key
                    # Hand-indexed: range() would allocate an iterator on this masked hot path.
                    index = 0
                    while index < take:
                        payload[write_offset + index] = (
                            chunk_view[cursor + index]
                            ^ mask_key[(write_offset + index) & 3]
                        )
                        index += 1
                else:
                    payload[write_offset:write_offset + take] = (
                        chunk_view[cursor : cursor + take]
                    )
                consumed += take
                write_offset += take
                self._payload_write_offset = write_offset
                if write_offset >= self.reported_length:
                    self.state = FrameParseState.FRAME_READY
                continue

            if state == FrameParseState.DRAINING_PAYLOAD:
                # Tier 3: count the bytes off the wire without storing or unmasking them.
                drain_remaining = self._drain_remaining
                take = drain_remaining if drain_remaining <= remaining else remaining
                consumed += take
                drain_remaining -= take
                self._drain_remaining = drain_remaining
                if drain_remaining == 0:
                    self.state = FrameParseState.FRAME_READY
                continue

            if state == FrameParseState.READING_HEADER:
                field_size = 2
            elif state == FrameParseState.READING_LEN16:
                field_size = 2
            elif state == FrameParseState.READING_LEN64:
                field_size = 8
            else:  # READING_MASK
                field_size = 4
            header_len = self._header_len
            need = field_size - header_len
            take = need if need <= remaining else remaining
            self._header_scratch[header_len : header_len + take] = (
                chunk_view[cursor : cursor + take]
            )
            header_len += take
            self._header_len = header_len
            consumed += take
            # Compare against the field's total size, not need: a split field would desync.
            if header_len < field_size:
                continue

            if state == FrameParseState.READING_HEADER:
                self._dispatch_header()
            elif state == FrameParseState.READING_LEN16:
                self.reported_length = struct.unpack("!H", self._header_view[:2])[0]
                self._header_len = 0
                self._after_length()
            elif state == FrameParseState.READING_LEN64:
                self.reported_length = struct.unpack("!Q", self._header_view)[0]
                self._header_len = 0
                self._after_length()
            else:  # READING_MASK
                self._mask_key = bytes(self._header_view[:4])
                self._header_len = 0
                self._after_mask()
        return consumed

    def _dispatch_header(self) -> None:
        first_byte = self._header_scratch[0]
        second_byte = self._header_scratch[1]
        self.fin = bool(first_byte & 0x80)
        self.rsv = (first_byte >> 4) & 0x07
        self.opcode = first_byte & 0x0F
        self.had_mask = bool(second_byte & 0x80)
        length_marker = second_byte & 0x7F

        if self.rsv != 0:
            raise self._fail(
                f"non-zero RSV bits {self.rsv:03b} (no extensions negotiated)",
            )
        if self.opcode in CONTROL_OPCODES:
            if not self.fin:
                raise self._fail(
                    f"control frame opcode 0x{self.opcode:x} must be FIN=1",
                )
        elif self.opcode not in DATA_OPCODES:
            raise self._fail(f"reserved opcode 0x{self.opcode:x}")

        self._header_len = 0
        if length_marker < 126:
            self.reported_length = length_marker
            self._after_length()
            return
        if length_marker == 126:
            self.state = FrameParseState.READING_LEN16
            return
        # length_marker == 127
        self.state = FrameParseState.READING_LEN64

    def _after_length(self) -> None:
        # RFC 6455 §5.5: control frames must be <= 125 bytes regardless of the cap.
        if self.opcode in CONTROL_OPCODES and self.reported_length > MAX_CONTROL_PAYLOAD_BYTES:
            raise self._fail(
                f"control frame opcode 0x{self.opcode:x} payload "
                f"{self.reported_length} > {MAX_CONTROL_PAYLOAD_BYTES}",
            )
        # Over-cap data frames enter tier-3 drain; a masked frame reads its mask first.
        if self.reported_length > self._max_payload_bytes:
            self.oversized = True
            self._drain_remaining = self.reported_length
            if self.had_mask:
                self.state = FrameParseState.READING_MASK
                return
            self._after_mask()
            return
        if self.had_mask:
            self.state = FrameParseState.READING_MASK
            return
        self._after_mask()

    def _after_mask(self) -> None:
        if self.oversized:
            # Tier 3: skip buffer setup; DRAINING_PAYLOAD counts the bytes off and discards.
            if self._drain_remaining == 0:
                self.state = FrameParseState.FRAME_READY
                return
            self.state = FrameParseState.DRAINING_PAYLOAD
            return
        if self.reported_length == 0:
            self.state = FrameParseState.FRAME_READY
            return
        # Frames that fit reuse the steady buffer; larger frames allocate once, freed at reset().
        if self.reported_length > self._payload_capacity:
            self._payload = bytearray(self.reported_length)
            self._payload_view = memoryview(self._payload)
        # else: _payload already aliases the steady buffer.
        self._payload_write_offset = 0
        self.state = FrameParseState.READING_PAYLOAD

    def _fail(self, message: str) -> WebSocketProtocolError:
        self.error = message
        self.state = FrameParseState.ERROR
        return WebSocketProtocolError(message)


def make_mask_key() -> bytes:
    """Return 4 random bytes for client-side outbound frame masking (RFC 6455 §5.3)."""
    return os.urandom(4)


def encode_frame(
    opcode: int,
    payload,
    *,
    fin: bool = True,
    mask: bytes | None = None,
) -> bytearray:
    """Encode a single websocket frame for outbound transmission.

    Args:
        opcode: One of ``OPCODE_*``.
        payload: Frame payload (``bytes``, ``bytearray``, or ``memoryview``); may be empty.
        fin: FIN bit; clear only on non-final frames of a fragmented message.
        mask: 4-byte key for client-side masking, or ``None`` for server-side.

    Returns:
        The encoded frame as a ``bytearray`` ready for ``socket.send``.

    Raises:
        WebSocketProtocolError: Control payload over 125 bytes, or *mask* is not 4 bytes.
    """
    if opcode in CONTROL_OPCODES and len(payload) > MAX_CONTROL_PAYLOAD_BYTES:
        raise WebSocketProtocolError(
            f"control frame opcode 0x{opcode:x} payload {len(payload)} "
            f"> {MAX_CONTROL_PAYLOAD_BYTES}",
        )
    if mask is not None and len(mask) != 4:
        raise WebSocketProtocolError(
            f"mask must be 4 bytes, got {len(mask)}",
        )

    first_byte = (0x80 if fin else 0x00) | (opcode & 0x0F)
    payload_length = len(payload)
    mask_bit = 0x80 if mask is not None else 0x00

    parts = bytearray()
    parts.append(first_byte)
    if payload_length < 126:
        parts.append(mask_bit | payload_length)
    elif payload_length <= 0xFFFF:
        parts.append(mask_bit | 126)
        _append_packed_h(parts, payload_length)
    else:
        parts.append(mask_bit | 127)
        _append_packed_q(parts, payload_length)
    if mask is not None:
        parts.extend(mask)
        payload_offset = len(parts)
        parts.extend(payload)
        # Hand-indexed: range() would allocate an iterator on every masked frame.
        index = 0
        while index < payload_length:
            parts[payload_offset + index] ^= mask[index & 3]
            index += 1
    else:
        parts.extend(payload)
    return parts


def encode_close_payload(code: int | None, reason: str = "") -> bytes:
    """Build the body of a CLOSE frame.

    Args:
        code: Status code (e.g. :data:`CLOSE_NORMAL`), or ``None`` for an empty payload.
        reason: UTF-8 string explaining the close.

    Returns:
        Bytes ready for :func:`encode_frame` with ``opcode=OPCODE_CLOSE``.

    Raises:
        WebSocketProtocolError: *code* is reserved, or the reason exceeds the 125-byte cap.
    """
    if code is None:
        if reason:
            raise WebSocketProtocolError(
                "cannot send a close reason without a code",
            )
        return b""
    if code in RESERVED_CLOSE_CODES:
        raise WebSocketProtocolError(
            f"close code {code} is reserved and must not be sent on the wire",
        )
    encoded_reason = reason.encode("utf-8")
    if 2 + len(encoded_reason) > MAX_CONTROL_PAYLOAD_BYTES:
        raise WebSocketProtocolError(
            f"close payload {2 + len(encoded_reason)} > "
            f"{MAX_CONTROL_PAYLOAD_BYTES}",
        )
    body = bytearray()
    _append_packed_h(body, code)
    body.extend(encoded_reason)
    return bytes(body)


def parse_close_payload(payload: bytes) -> tuple[int | None, str]:
    """Decode a CLOSE-frame body into ``(code, reason)``.

    Args:
        payload: Raw body of an inbound CLOSE frame.

    Returns:
        ``(None, "")`` for an empty body, else ``(code, reason)``.

    Raises:
        WebSocketProtocolError: 1-byte body, reserved code, or non-UTF-8 reason.
    """
    if not payload:
        return None, ""
    if len(payload) == 1:
        raise WebSocketProtocolError(
            "close payload of exactly 1 byte is forbidden by RFC 6455 §5.5.1",
        )
    code = struct.unpack_from("!H", payload)[0]
    if code in RESERVED_CLOSE_CODES:
        raise WebSocketProtocolError(
            f"peer sent reserved close code {code}",
        )
    try:
        reason = str(payload[2:], "utf-8")
    except UnicodeError as decode_error:
        raise WebSocketProtocolError(
            f"close reason is not valid UTF-8: {decode_error}",
        ) from decode_error
    return code, reason


def validate_text_payload(payload: bytes) -> str:
    """Decode and UTF-8-validate a text-frame payload.

    Args:
        payload: Raw text-frame payload bytes.

    Returns:
        Decoded ``str``.

    Raises:
        WebSocketProtocolError: Bytes are not valid UTF-8.
    """
    try:
        return str(payload, "utf-8")
    except UnicodeError as decode_error:
        raise WebSocketProtocolError(
            f"text payload is not valid UTF-8: {decode_error}",
        ) from decode_error
