"""WebSocket wire format for chumicro-websockets.

Consolidates URL parsing, opening-handshake encoders and parsers
(both client- and server-side), the case-insensitive header dict,
the streaming binary frame parser, the frame encoder, the close
payload codec, and the exception hierarchy.  Wire-format primitives
in one file (bytes-on-the-wire); orchestration in another.

No socket I/O here.  The client / server drives the socket and
feeds bytes in.

v1 scope:

* RFC 6455 framing — opcodes 0/1/2/8/9/A, 7 / 16 / 64-bit length,
  client masking, inbound fragmentation, control-frame interleave.
* UTF-8 validation on text frames per RFC 6455 §8.1.
* Outbound is always single-frame (``FIN=1``).
* No permessage-deflate, no subprotocol negotiation, no extensions.
"""

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
    """Return ``sha1(data).digest()`` via whichever hashlib path the
    runtime exposes.

    CPython + MicroPython expose ``hashlib.sha1``; CircuitPython gates
    it off (``MICROPY_PY_HASHLIB_SHA1=0``) but the mbedtls-backed
    ``hashlib.new("sha1", data)`` factory works.  A runtime exposing
    neither surfaces as a clear ``AttributeError`` here, which is the
    right failure mode — don't silently fall back to pure-Python and
    fragment the embedded heap.
    """
    hasher_factory = getattr(hashlib, "sha1", None)
    if hasher_factory is not None:
        return hasher_factory(data).digest()
    return hashlib.new("sha1", data).digest()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class WebSocketError(Exception):
    """Base class for every chumicro-websockets failure."""


class WebSocketProtocolError(WebSocketError):
    """Peer sent bytes the spec doesn't allow — anything RFC 6455 calls
    out as MUST close.  Right response: close with
    :data:`CLOSE_PROTOCOL_ERROR` (or :data:`CLOSE_BAD_DATA` for UTF-8).
    """


class WebSocketHandshakeError(WebSocketError):
    """Opening-handshake failed — non-101 status, wrong accept token,
    missing/wrong ``Upgrade``/``Connection`` headers, or malformed
    HTTP/1.1 (server-side: bad method/version/key).
    """


class WebSocketURLError(WebSocketError):
    """URL doesn't parse as a supported ``ws://`` / ``wss://`` URL."""


class WebSocketTimeoutError(WebSocketError):
    """A per-phase timeout elapsed (handshake, close, or pong-after-ping)."""


class WebSocketBackpressureError(WebSocketError):
    """TX queue overflowed (more than ``max_tx_queue_size`` outbound
    frames enqueued before the runner could drain them).
    """


class WebSocketStateError(WebSocketError):
    """Caller invoked an operation that requires a different state
    (e.g., ``send_text`` before OPEN, ``connect`` after OPEN).
    """


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: RFC 6455 §1.3 magic GUID.  Concatenated with the client's nonce
#: and SHA-1'd to derive ``Sec-WebSocket-Accept``.
WS_MAGIC_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

#: RFC 6455 §4.1 — required version token for the opening handshake.
WS_VERSION = "13"

#: HTTP/1.1 line terminator.
CRLF = b"\r\n"

#: Header / body separator.
CRLF_CRLF = b"\r\n\r\n"

#: Default per-tick recv cap.  Mirrors :data:`chumicro_mqtt.MQTTClient`
#: and :data:`chumicro_requests.HttpClient`; keeps tick latency
#: LED-friendly.
DEFAULT_RECV_BUDGET_PER_TICK = const(1024)

#: Default per-tick send cap.
DEFAULT_SEND_BUDGET_PER_TICK = const(1024)

#: Default cap on inbound message size.  16 KB leaves headroom on a
#: 256 KB MCU RAM minimum board.
DEFAULT_MAX_MESSAGE_BYTES = const(16384)

#: Default bound on the outbound TX queue.
DEFAULT_MAX_TX_QUEUE_SIZE = const(8)

#: Default steady-state payload buffer size for :class:`FrameParser`.
#: Sized to cover the common short text/binary frame without per-frame
#: allocation; frames bigger than this fall back to a one-shot
#: ``bytearray(payload_length)``.  Same trade-off as
#: :data:`chumicro_mqtt._wire.DEFAULT_RX_BUFFER_SIZE`.
DEFAULT_PAYLOAD_BUFFER_SIZE = const(256)

#: Default opening-handshake budget in ms.
DEFAULT_HANDSHAKE_TIMEOUT_MS = const(10000)

#: Default close-handshake budget in ms.
DEFAULT_CLOSE_TIMEOUT_MS = const(5000)

#: Default pong-after-ping budget in ms.
DEFAULT_PONG_TIMEOUT_MS = const(30000)

#: RFC 6455 §5.5 — control payloads MUST be <=125 bytes.
MAX_CONTROL_PAYLOAD_BYTES = const(125)

# Opcodes — RFC 6455 §5.2.
OPCODE_CONTINUATION = const(0x0)
OPCODE_TEXT = const(0x1)
OPCODE_BINARY = const(0x2)
OPCODE_CLOSE = const(0x8)
OPCODE_PING = const(0x9)
OPCODE_PONG = const(0xA)

#: Opcodes that carry data (vs. control).  RFC 6455 §5.6.
DATA_OPCODES = frozenset({OPCODE_CONTINUATION, OPCODE_TEXT, OPCODE_BINARY})

#: Opcodes that are control frames.  RFC 6455 §5.5 — MUST be ``FIN=1``,
#: payload <=125 bytes, may interleave between fragmented data frames.
CONTROL_OPCODES = frozenset({OPCODE_CLOSE, OPCODE_PING, OPCODE_PONG})

# Close codes — RFC 6455 §7.4.1 / §7.4.2.
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

#: Close codes the spec forbids on the wire (RFC 6455 §7.4.1) —
#: a peer-supplied close code matching one of these is itself a
#: protocol error.
RESERVED_CLOSE_CODES = frozenset({
    CLOSE_NO_STATUS_RCVD,
    CLOSE_ABNORMAL,
    CLOSE_TLS_HANDSHAKE,
})


# ---------------------------------------------------------------------------
# WebSocketState
# ---------------------------------------------------------------------------


class WebSocketState:
    """Lifecycle states for a websocket session.

    Forward-only ``CONNECTING -> OPEN -> CLOSING -> CLOSED``; either
    side may shortcut to ``CLOSED`` if the opening handshake fails.
    """

    CONNECTING = "connecting"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


# ---------------------------------------------------------------------------
# Case-insensitive header dict
# ---------------------------------------------------------------------------


class CaseInsensitiveDict:
    """Header dict whose lookups fold to lowercase.

    HTTP/1.1 §3.2 requires header names to be case-insensitive on
    receipt — the websocket opening handshake is HTTP/1.1.  We store
    the original-cased name (so callers see ``Upgrade`` not
    ``upgrade``) keyed off the lowercased form.  ``items()`` yields
    in insertion order on every runtime — MicroPython and CircuitPython
    dicts do not preserve insertion order unlike CPython 3.7+, so a
    paired ``_order`` list of lowercase keys drives iteration.  Mirrors
    the order-preserving shape in
    :class:`chumicro_requests._wire.CaseInsensitiveDict` so the WS
    opening handshake emits headers in the same order it accepted them
    on every runtime; without ``_order`` the handshake on MP / CP
    randomized header order vs. CPython tests.

    Slim subset (no ``__iter__`` / ``__len__`` / ``__eq__`` / ``__repr__``
    / ``add()``) since the WS encoders + parsers only need the methods
    below.  Inlined from chumicro-requests per the copy-don't-couple
    rule until a third HTTP/1.1-aware consumer (http_server is the
    third — re-evaluate at next workspace audit) triggers extracting
    a shared ``chumicro-http`` package.
    """

    def __init__(self):
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


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------


def parse_ws_url(url: str) -> tuple[str, str, int, str]:
    """Split a ``ws://`` / ``wss://`` *url* into ``(scheme, host, port, path)``.

    *path* always starts with ``/`` and includes the query string if
    present.  Raises :class:`WebSocketURLError` on bad scheme, missing
    host, or out-of-range port.  Examples::

        ws://example.com/      -> ("ws", "example.com", 80, "/")
        wss://api.host:8443/v1 -> ("wss", "api.host", 8443, "/v1")
        ws://h/p?q=1           -> ("ws", "h", 80, "/p?q=1")
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


# ---------------------------------------------------------------------------
# Handshake key derivation
# ---------------------------------------------------------------------------


def make_websocket_key() -> str:
    """Generate a fresh ``Sec-WebSocket-Key`` per RFC 6455 §4.1
    (16 random bytes, base64-encoded as ASCII ``str``).
    """
    nonce = os.urandom(16)
    encoded = binascii.b2a_base64(nonce)
    # b2a_base64 appends a trailing newline byte.
    return encoded.rstrip(b"\n").rstrip(b"\r").decode("ascii")


def derive_accept_key(client_key: str) -> str:
    """Compute ``Sec-WebSocket-Accept`` from the client's nonce.

    RFC 6455 §4.2.2: ``base64(sha1(client_key + WS_MAGIC_GUID))``.
    *client_key* is the verbatim base64 nonce — do not decode first.
    """
    digest = _sha1_digest((client_key + WS_MAGIC_GUID).encode("ascii"))
    encoded = binascii.b2a_base64(digest)
    return encoded.rstrip(b"\n").rstrip(b"\r").decode("ascii")


# ---------------------------------------------------------------------------
# Handshake encoders
# ---------------------------------------------------------------------------


def _merge_extra_headers(merged: "CaseInsensitiveDict", extra_headers) -> None:
    """Merge caller-supplied headers into *merged* in insertion order.

    Accepts a :class:`CaseInsensitiveDict`, a plain ``dict``, or any
    iterable of ``(name, value)`` pairs.  ``None`` is a no-op.
    """
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

    *port* is appended to ``Host:`` only when non-default (80/443).
    *extra_headers* (iterable / ``dict`` / :class:`CaseInsensitiveDict`)
    is merged in first; the five mandatory upgrade headers are
    re-applied at the end so callers can't accidentally break the
    handshake.
    """
    is_default_port = port in (80, 443)
    host_value = host if is_default_port else f"{host}:{port}"

    merged = CaseInsensitiveDict()
    _merge_extra_headers(merged, extra_headers)
    # Mandatory upgrade headers — applied AFTER caller's so they win.
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

    *client_key* is the verbatim ``Sec-WebSocket-Key`` from the request;
    *extra_headers* is merged in first, then the three mandatory
    upgrade headers (``Upgrade``, ``Connection``, ``Sec-WebSocket-Accept``)
    are re-applied at the end so they can't be overridden.
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
    """Encode a regular HTTP/1.1 error response for a rejected WS
    upgrade (wrong path, missing header, unsupported version) — sent
    instead of ``101`` and the connection then closes.
    ``Content-Length`` is auto-added when *body* is set.
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


# ---------------------------------------------------------------------------
# Streaming handshake parsers
# ---------------------------------------------------------------------------


class HandshakeParseState:
    """Streaming-handshake parser states.

    Forward-only.  ``REQUEST_LINE`` is the server-side first line
    (``GET /path HTTP/1.1``); ``STATUS_LINE`` is the client-side
    first line (``HTTP/1.1 101 Switching Protocols``).  Both then
    flow through ``HEADERS`` to ``DONE``.  ``ERROR`` is terminal.
    """

    REQUEST_LINE = "request_line"
    STATUS_LINE = "status_line"
    HEADERS = "headers"
    DONE = "done"
    ERROR = "error"


class _HandshakeLineParser:
    """Shared scaffolding for the streaming HTTP/1.1 first-line + header
    parsers used by both sides of the websocket opening handshake.

    Subclasses override :attr:`_initial_state`, :meth:`_parse_first_line`,
    and :meth:`_finalize`.  The base handles buffering, CRLF-bounded
    line extraction, the cap on buffered bytes, header line parsing,
    and the ``ERROR`` transition.
    """

    _initial_state: str = ""

    def __init__(self, *, max_header_bytes: int = 8192):
        self._max_header_bytes = max_header_bytes
        self._buffer = bytearray()
        # Read cursor into ``_buffer`` — same pattern as
        # :class:`chumicro_requests._wire.ResponseParser`.  Per-line
        # ``_buffer = bytearray(_buffer[N:])`` was the 1024-tier
        # fragmentation source on Lolin S2 ESP32-S2.  See on-device
        # tests in ``functional_tests/test_memory_fragmentation_on_device.py``.
        self._read_offset = 0
        self.state = self._initial_state
        self.http_version = ""
        self.headers = CaseInsensitiveDict()
        self.error = None
        self.leftover = b""


    def feed(self, chunk: bytes) -> None:
        """Consume *chunk* bytes; advance state if possible.

        Raises :class:`WebSocketHandshakeError` on overflow, malformed
        first line, or any subclass validation failure (and transitions
        to ``ERROR``).
        """
        if self.state in (HandshakeParseState.DONE, HandshakeParseState.ERROR):
            return
        self._buffer.extend(chunk)
        # Cap is on *unconsumed* bytes — the cursor amortizes the
        # bytearray reuse, so checking ``len(_buffer)`` would over-count
        # bytes the cursor has logically dropped but the compaction step
        # hasn't reclaimed yet.
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
        in-place memmove on every runtime — no allocation.  See
        :meth:`chumicro_requests._wire.ResponseParser._consume` for the
        original allocating shape this replaces.
        """
        self._read_offset += count
        if self._read_offset > 0 and self._read_offset * 2 >= len(self._buffer):
            self._buffer[:self._read_offset] = b""
            self._read_offset = 0

    def _parse_header_line(self, line: bytes) -> None:
        decoded = line.decode("iso-8859-1")
        colon_index = decoded.find(":")
        if colon_index == -1:
            raise self._fail(f"header line missing colon: {decoded!r}")
        header_name = decoded[:colon_index].strip()
        header_value = decoded[colon_index + 1:].strip()
        if not header_name:
            raise self._fail(f"empty header name in {decoded!r}")
        self.headers[header_name] = header_value

    def _validate_upgrade_headers(self, role_label: str) -> None:
        """Check the two upgrade headers shared by both sides."""
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
        """Stash remaining buffered bytes as :attr:`leftover` + transition DONE."""
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
    """Streaming parser for the server's HTTP/1.1 ``101`` response.

    Validates: status is ``101``, ``Upgrade``/``Connection`` carry the
    upgrade tokens, and ``Sec-WebSocket-Accept`` matches *expected_accept*
    (derived from the client's nonce).
    """

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
        # "HTTP/1.1 101 Switching Protocols" — split on first two spaces.
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
    """Streaming parser for the client's HTTP/1.1 upgrade request.

    Validates: method is ``GET``, version is ``HTTP/1.1+``,
    ``Upgrade``/``Connection`` carry the upgrade tokens,
    ``Sec-WebSocket-Version`` is ``13``, and ``Sec-WebSocket-Key`` is
    present + base64-decodes to 16 bytes.
    """

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
        # ``binascii.Error`` subclasses ``ValueError`` on CPython;
        # MicroPython raises ``ValueError`` directly.  Catch the parent.
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


# ---------------------------------------------------------------------------
# Frame parsing
# ---------------------------------------------------------------------------


class FrameParseState:
    """Streaming binary-frame parser states.

    One frame at a time::

        READING_HEADER -> [READING_LEN16 | READING_LEN64]
                       -> [READING_MASK]
                       -> [READING_PAYLOAD | DRAINING_PAYLOAD]
                       -> FRAME_READY
                       \\-> ERROR (any state)

    After ``FRAME_READY``, the caller reads :attr:`fin` /
    :attr:`opcode` / :attr:`payload` / :attr:`oversized`, then calls
    :meth:`reset` to return to ``READING_HEADER`` for the next frame.

    ``DRAINING_PAYLOAD`` is the tier-3 sink: payload bytes flow
    through without being stored.  Entered when the declared frame
    length exceeds ``max_payload_bytes``; on completion the frame
    arrives at ``FRAME_READY`` with :attr:`oversized` set and
    :attr:`payload` == ``b""``.
    """

    READING_HEADER = "reading_header"
    READING_LEN16 = "reading_len16"
    READING_LEN64 = "reading_len64"
    READING_MASK = "reading_mask"
    READING_PAYLOAD = "reading_payload"
    DRAINING_PAYLOAD = "draining_payload"
    FRAME_READY = "frame_ready"
    ERROR = "error"


class FrameParser:
    """Streaming RFC 6455 §5 binary-frame parser.

    One frame at a time — the higher layers (client / server) handle
    fragmentation reassembly, control-frame routing, mask-direction
    policy, and UTF-8 validation.

    Three-tier inbound size handling mirrors
    :class:`chumicro_mqtt._wire.PacketDecoder`:

    * **Tier 1 — steady.**  Frame payload ≤ ``payload_buffer_size``.
      Reuses the pre-allocated steady-state buffer.  No allocation.
    * **Tier 2 — intact.**  Frame payload > ``payload_buffer_size``
      but ≤ ``max_payload_bytes``.  One-shot ``bytearray(payload_length)``
      allocated for this frame, dropped on the next :meth:`reset`.
    * **Tier 3 — oversized.**  Frame payload > ``max_payload_bytes``.
      No allocation beyond the steady-state buffer; payload bytes are
      consumed off the wire without being stored (rolling discard).
      :attr:`oversized` is set on ``FRAME_READY`` and :attr:`payload`
      returns ``b""``.  The higher layer applies its ``WhenOversized``
      policy on the empty frame — matches the shared cross-library
      contract with ``chumicro-mqtt`` and ``chumicro-requests``,
      where ``DROP_WITH_EVENT`` drops the oversized payload and
      stays connected for the next inbound unit.

    Args:
        max_payload_bytes: Per-frame payload cap.  Frames declaring a
            larger length enter tier 3 (rolling discard); the parser
            stays usable for the next frame.  This bounds heap, not
            connection lifetime — a hostile peer can still trickle a
            multi-GB declared length, which the session layer's
            ``WhenOversized=DISCONNECT`` policy is the answer to.

    Public state on :attr:`state` == ``FRAME_READY``:

    * :attr:`fin`        — bool, FIN bit
    * :attr:`rsv`        — int, three RSV bits packed (RSV1<<2|RSV2<<1|RSV3)
    * :attr:`opcode`     — int (one of ``OPCODE_*``)
    * :attr:`had_mask`   — bool (was MASK bit set?)
    * :attr:`payload`    — ``bytes`` of unmasked payload (``b""`` on tier 3)
    * :attr:`oversized`  — bool, payload was drained without buffering
    * :attr:`reported_length` — int, declared frame length (load-bearing
      on tier 3, where :attr:`payload` is empty)
    """

    def __init__(
        self,
        *,
        max_payload_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        payload_buffer_size: int = DEFAULT_PAYLOAD_BUFFER_SIZE,
    ):
        self._max_payload_bytes = max_payload_bytes
        self.state = FrameParseState.READING_HEADER
        self._buffer = bytearray()
        self.fin =False
        self.rsv = 0
        self.opcode = 0
        self.had_mask = False
        self._payload_length = 0
        self._mask_key = b""
        # Steady-state payload buffer reused across frames — same shape
        # as :class:`chumicro_mqtt._wire.PacketDecoder`.  Frames whose
        # payload fits in ``payload_buffer_size`` reuse the buffer
        # (zero alloc per frame).  Tier-2 frames fall back to a
        # one-shot ``bytearray(payload_length)`` that gets dropped on
        # the next :meth:`reset`.  Tier-3 frames stay in the steady
        # buffer and discard.  ``_payload_view`` is the cached
        # memoryview so per-write slice indexing doesn't construct a
        # fresh view object every call; refreshed only when ``_payload``
        # rebinds to a one-shot oversized buffer.  Live-board signal
        # came from ``test_short_text_frame_no_leak_no_fragmentation
        # _on_device``: per-frame ``bytearray(N)`` was the residual
        # fragmentation source after the recv-buffer fix.
        self._payload_buffer = bytearray(payload_buffer_size)
        self._payload_buffer_view = memoryview(self._payload_buffer)
        self._payload_capacity = payload_buffer_size
        self._payload = self._payload_buffer
        self._payload_view = self._payload_buffer_view
        self._payload_write_offset = 0
        # Tier-3 state.  ``oversized`` flips true at length-byte time
        # for any frame whose declared length exceeds
        # ``max_payload_bytes``; ``_drain_remaining`` counts payload
        # bytes still to consume off the wire.
        self.oversized = False
        self._drain_remaining = 0
        self.error = None

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------

    @property
    def payload(self):
        """Unmasked payload of the just-completed frame as ``bytes``.

        Returns ``b""`` until :attr:`state` == ``FRAME_READY``, and
        also ``b""`` on tier-3 frames — see :attr:`oversized` and
        :attr:`reported_length` for the size the peer declared.  Reads
        through the cached ``_payload_view`` (zero-copy memoryview slice)
        and snapshots one ``bytes`` copy for the caller — handlers may
        ``.decode()`` the result, which memoryview lacks.
        """
        return bytes(self._payload_view[:self._payload_write_offset])

    @property
    def reported_length(self):
        """Frame length the peer declared (load-bearing on tier-3
        frames where :attr:`payload` was drained without being stored).
        """
        return self._payload_length

    # ------------------------------------------------------------------
    # Driving
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Return to ``READING_HEADER`` for the next frame.

        Discards the just-finished frame's metadata + payload.  Rebinds
        ``_payload`` to the steady-state ``_payload_buffer`` (no alloc);
        any one-shot tier-2 buffer from the prior frame is now
        unreferenced and GC-eligible.  Clears tier-3 drain state.
        """
        self.state = FrameParseState.READING_HEADER
        self._buffer = bytearray()
        self.fin =False
        self.rsv = 0
        self.opcode = 0
        self.had_mask = False
        self._payload_length = 0
        self._mask_key = b""
        self._payload = self._payload_buffer
        self._payload_view = self._payload_buffer_view
        self._payload_write_offset = 0
        self.oversized = False
        self._drain_remaining = 0

    def feed(self, chunk: bytes, start: int = 0) -> int:
        """Consume bytes from *chunk* starting at *start*; return how many
        were used (relative to *start*).

        *start* lets a caller feed the same buffer across multiple
        per-frame passes without slicing it each iteration — the inner
        loop in :meth:`chumicro_websockets._session._BaseSession._feed_frame_bytes`
        used to ``chunk[offset:]`` per pass, which allocated a fresh
        memoryview window each time.

        Per-state chunked consumption — header / length / mask states
        copy the bytes they need in one slice, payload state extends
        the buffer by ``min(remaining, payload_remaining)`` per pass.
        Tier-3 payloads (length > ``max_payload_bytes``) drain through
        the parser without being stored; :attr:`oversized` flips true
        and :attr:`payload` returns ``b""`` at ``FRAME_READY``.

        The parser stops consuming when it transitions to
        ``FRAME_READY`` so any leftover bytes remain available to the
        caller for the next frame.

        Raises:
            WebSocketProtocolError: Reserved opcode, control frame
                with payload >125, or control frame with FIN=0.  The
                parser also transitions to ``ERROR`` and stores the
                message in :attr:`error`.  Oversized data frames do
                NOT raise — they enter tier-3 drain.
        """
        consumed = 0
        effective_length = len(chunk) - start
        # Bind memoryview once so each per-state slice is zero-copy on
        # the source side.  Skip when the chunk is itself a memoryview
        # (callers like ``_session._recv_chunk`` already pass a view).
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
                need = self._payload_length - write_offset
                take = need if need <= remaining else remaining
                if self.had_mask:
                    mask_key = self._mask_key
                    for index in range(take):
                        payload[write_offset + index] = (
                            chunk_view[cursor + index]
                            ^ mask_key[(write_offset + index) & 3]
                        )
                else:
                    payload[write_offset:write_offset + take] = (
                        chunk_view[cursor : cursor + take]
                    )
                consumed += take
                write_offset += take
                self._payload_write_offset = write_offset
                if write_offset >= self._payload_length:
                    self.state = FrameParseState.FRAME_READY
                continue

            if state == FrameParseState.DRAINING_PAYLOAD:
                # Tier 3: count the bytes off the wire, don't store
                # them, don't unmask them (the bytes are discarded
                # either way).
                drain_remaining = self._drain_remaining
                take = drain_remaining if drain_remaining <= remaining else remaining
                consumed += take
                drain_remaining -= take
                self._drain_remaining = drain_remaining
                if drain_remaining == 0:
                    self.state = FrameParseState.FRAME_READY
                continue

            if state == FrameParseState.READING_HEADER:
                need = 2 - len(self._buffer)
            elif state == FrameParseState.READING_LEN16:
                need = 2 - len(self._buffer)
            elif state == FrameParseState.READING_LEN64:
                need = 8 - len(self._buffer)
            else:  # READING_MASK
                need = 4 - len(self._buffer)
            take = need if need <= remaining else remaining
            self._buffer.extend(chunk_view[cursor : cursor + take])
            consumed += take
            if len(self._buffer) < need:
                continue

            if state == FrameParseState.READING_HEADER:
                self._dispatch_header()
            elif state == FrameParseState.READING_LEN16:
                self._payload_length = struct.unpack("!H", self._buffer)[0]
                self._buffer = bytearray()
                self._after_length()
            elif state == FrameParseState.READING_LEN64:
                self._payload_length = struct.unpack("!Q", self._buffer)[0]
                self._buffer = bytearray()
                self._after_length()
            else:  # READING_MASK
                self._mask_key = bytes(self._buffer)
                self._buffer = bytearray()
                self._after_mask()
        return consumed

    def _dispatch_header(self) -> None:
        first_byte = self._buffer[0]
        second_byte = self._buffer[1]
        self.fin =bool(first_byte & 0x80)
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

        self._buffer = bytearray()
        if length_marker < 126:
            self._payload_length = length_marker
            self._after_length()
            return
        if length_marker == 126:
            self.state = FrameParseState.READING_LEN16
            return
        # length_marker == 127
        self.state = FrameParseState.READING_LEN64

    def _after_length(self) -> None:
        # RFC 6455 §5.5: control frames MUST be ≤ 125 bytes.  This is
        # a protocol violation regardless of ``max_payload_bytes``, so
        # it still raises — the connection must close with 1002.
        if self.opcode in CONTROL_OPCODES and self._payload_length > MAX_CONTROL_PAYLOAD_BYTES:
            raise self._fail(
                f"control frame opcode 0x{self.opcode:x} payload "
                f"{self._payload_length} > {MAX_CONTROL_PAYLOAD_BYTES}",
            )
        # Data frame > max_payload_bytes — enter tier-3 drain instead
        # of raising.  The session layer's ``WhenOversized`` policy
        # decides whether to stay connected.  Mask state must still
        # be consumed off the wire if MASK was set, since the 4 mask
        # bytes precede the payload bytes.
        if self._payload_length > self._max_payload_bytes:
            self.oversized = True
            self._drain_remaining = self._payload_length
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
            # Tier 3: skip the steady/intact buffer setup entirely.
            # Payload bytes will be counted off and discarded by the
            # ``DRAINING_PAYLOAD`` branch of :meth:`feed`.
            if self._drain_remaining == 0:
                self.state = FrameParseState.FRAME_READY
                return
            self.state = FrameParseState.DRAINING_PAYLOAD
            return
        if self._payload_length == 0:
            self.state = FrameParseState.FRAME_READY
            return
        # Reuse the steady-state payload buffer when the frame fits
        # (tier 1).  Only tier 2 pays a per-frame allocation, and that
        # one-shot bytearray is released on the next :meth:`reset`.
        if self._payload_length > self._payload_capacity:
            self._payload = bytearray(self._payload_length)
            self._payload_view = memoryview(self._payload)
        # else: ``_payload`` / ``_payload_view`` already alias the
        # steady-state buffer from :meth:`__init__` / :meth:`reset`.
        self._payload_write_offset = 0
        self.state = FrameParseState.READING_PAYLOAD

    def _fail(self, message: str) -> WebSocketProtocolError:
        self.error = message
        self.state = FrameParseState.ERROR
        return WebSocketProtocolError(message)


# ---------------------------------------------------------------------------
# Frame encoding
# ---------------------------------------------------------------------------


def make_mask_key() -> bytes:
    """Return 4 random bytes for client-side outbound frame masking.

    Per RFC 6455 §5.3 — the mask is a random 32-bit value freshly
    chosen for each frame.  Predictability undermines the masking
    purpose (cache-poisoning protection on intermediaries).
    """
    return os.urandom(4)


def encode_frame(
    opcode: int,
    payload: bytes,
    *,
    fin: bool = True,
    mask: bytes | None = None,
) -> bytes:
    """Encode a single websocket frame for outbound transmission.

    Args:
        opcode: One of ``OPCODE_*`` (``OPCODE_TEXT``, ``OPCODE_BINARY``,
            ``OPCODE_PING``, ``OPCODE_PONG``, ``OPCODE_CLOSE``,
            ``OPCODE_CONTINUATION``).
        payload: Frame payload as ``bytes``.  Empty allowed.
        fin: Whether this is the final frame of a message.  Always
            ``True`` in v1 outbound (no outbound fragmentation).
            Exposed for tests.
        mask: ``None`` for server-side (no masking).  4-byte key
            (typically from :func:`make_mask_key`) for client-side.
            Per RFC 6455 §5.1, clients MUST mask outbound frames and
            servers MUST NOT.

    Returns:
        Encoded frame as ``bytes`` ready for ``socket.send``.

    Raises:
        WebSocketProtocolError: Control frame opcode with payload
            >125 bytes, or *mask* is the wrong length.
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
        for index in range(payload_length):
            parts[payload_offset + index] ^= mask[index & 3]
    else:
        parts.extend(payload)
    return bytes(parts)


# ---------------------------------------------------------------------------
# Close payload codec
# ---------------------------------------------------------------------------


def encode_close_payload(code: int | None, reason: str = "") -> bytes:
    """Build the body of a CLOSE frame.

    Per RFC 6455 §5.5.1: empty body OR 2-byte big-endian status
    code optionally followed by a UTF-8 reason.  Reason is capped
    so the whole payload stays <=125 bytes (control-frame limit).

    Args:
        code: Status code (e.g. :data:`CLOSE_NORMAL`).  ``None`` for
            an empty close payload.
        reason: UTF-8 string explaining the close.

    Returns:
        Bytes ready for :func:`encode_frame` with ``opcode=OPCODE_CLOSE``.

    Raises:
        WebSocketProtocolError: Code is in :data:`RESERVED_CLOSE_CODES`
            (1005 / 1006 / 1015 — RFC 6455 §7.4.1 forbids these on
            the wire), or reason encoded would push the body past
            125 bytes.
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
        ``(None, "")`` when *payload* is empty.  Otherwise
        ``(code, reason)`` with *code* the 2-byte big-endian
        status code and *reason* the UTF-8 string that follows.

    Raises:
        WebSocketProtocolError: Length is exactly 1 (must be 0 or
            >=2 per RFC 6455 §5.5.1), code is in
            :data:`RESERVED_CLOSE_CODES`, or reason bytes are not
            valid UTF-8 (RFC 6455 §8.1 — close reason MUST be UTF-8).
    """
    if not payload:
        return None, ""
    if len(payload) == 1:
        raise WebSocketProtocolError(
            "close payload of exactly 1 byte is forbidden by RFC 6455 §5.5.1",
        )
    code = struct.unpack("!H", payload[:2])[0]
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
    """Decode + UTF-8-validate a text-frame payload.

    Per RFC 6455 §8.1, text frames MUST contain valid UTF-8.  Invalid
    bytes are a protocol error and the connection MUST close with
    :data:`CLOSE_BAD_DATA`.

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
