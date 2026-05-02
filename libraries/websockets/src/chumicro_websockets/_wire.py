"""WebSocket wire format for chumicro-websockets.

Consolidates URL parsing, opening-handshake encoders and parsers
(both client- and server-side), the case-insensitive header dict,
the streaming binary frame parser, the frame encoder, the close
payload codec, and the exception hierarchy.  Mirrors the post-
Decision-0029 :mod:`chumicro_requests._wire` shape — one file of
bytes-on-the-wire, one file of orchestration.

No socket I/O here.  The client / server drives the socket and
feeds bytes in.

v1 scope (Decision 0045):

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


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class WebSocketError(Exception):
    """Base class for every chumicro-websockets failure."""


class WebSocketProtocolError(WebSocketError):
    """Peer sent bytes the spec doesn't allow.

    Reserved opcode, missing/forbidden mask, fragmented control
    frame, control payload >125 bytes, invalid close-frame body,
    text frame with invalid UTF-8, length encoded with non-minimal
    width — anything RFC 6455 calls out as MUST close.  Always a
    peer or network bug; the right response is close with
    :data:`CLOSE_PROTOCOL_ERROR` (or :data:`CLOSE_BAD_DATA` for
    UTF-8 failures) and surface the error to the caller.
    """


class WebSocketHandshakeError(WebSocketError):
    """Opening-handshake failed.

    Server sent a non-101 status, missing/wrong ``Sec-WebSocket-Accept``,
    missing ``Upgrade: websocket`` / ``Connection: Upgrade``, or the
    handshake bytes weren't well-formed HTTP/1.1.  Server-side: the
    client's request was missing required upgrade headers, used the
    wrong method, or quoted a key that wasn't a 16-byte base64 nonce.
    """


class WebSocketURLError(WebSocketError):
    """URL doesn't parse as a supported ``ws://`` / ``wss://`` URL."""


class WebSocketTimeoutError(WebSocketError):
    """A per-phase timeout budget elapsed.

    Opening-handshake budget (``handshake_timeout_ms``), close-handshake
    budget (``close_timeout_ms``), or pong-after-ping budget
    (``pong_timeout_ms``).
    """


class WebSocketBackpressureError(WebSocketError):
    """TX queue overflowed when ``when_oversized=DISCONNECT``.

    Mirrors :class:`chumicro_mqtt.MQTTBackpressureError` — caller
    enqueued more than ``max_tx_queue_size`` outbound frames before
    the runner could drain them.
    """


class WebSocketOversizedError(WebSocketError):
    """Inbound message exceeded ``max_message_bytes``.

    Raised when ``when_oversized=DISCONNECT`` (Decision 0045 §6).
    The other policies (``DROP_SILENT``, ``DROP_WITH_EVENT``) drop
    the payload silently or fire ``on_oversized`` without raising,
    then close the connection with :data:`CLOSE_TOO_BIG`.
    """


class WebSocketStateError(WebSocketError):
    """Caller invoked an operation that requires a different state.

    Examples: ``send_text`` before the connection reaches
    :data:`WebSocketState.OPEN`, or ``connect`` on a client already in
    :data:`WebSocketState.OPEN`.
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

#: Default per-tick recv cap — Decision 0045 §6.  Mirrors
#: :data:`chumicro_mqtt.MQTTClient` and
#: :data:`chumicro_requests.HttpClient`; keeps tick latency
#: LED-friendly.
DEFAULT_RECV_BUDGET_PER_TICK = const(1024)

#: Default per-tick send cap — Decision 0045 §6.
DEFAULT_SEND_BUDGET_PER_TICK = const(1024)

#: Default cap on inbound message size — Decision 0045 §6.  16 KB
#: leaves headroom on a Decision 0015 minimum board (256 KB MCU RAM).
DEFAULT_MAX_MESSAGE_BYTES = const(16384)

#: Default bound on the outbound TX queue — Decision 0045 §6.
DEFAULT_MAX_TX_QUEUE_SIZE = const(8)

#: Default opening-handshake budget in ms — Decision 0045 §6.
DEFAULT_HANDSHAKE_TIMEOUT_MS = const(10000)

#: Default close-handshake budget in ms — Decision 0045 §6.
DEFAULT_CLOSE_TIMEOUT_MS = const(5000)

#: Default pong-after-ping budget in ms — Decision 0045 §6.
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
    """Lifecycle states for a websocket session — Decision 0045 §5.

    Forward-only::

        CONNECTING -> OPEN -> CLOSING -> CLOSED

    Either side may shortcut directly from ``CONNECTING`` to
    ``CLOSED`` if the opening handshake fails.
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
    receipt — the websocket opening handshake is HTTP/1.1.  We
    store the original-cased name (so callers see ``Upgrade`` not
    ``upgrade``) keyed off the lowercased form.

    Inlined copy of :class:`chumicro_requests._wire.CaseInsensitiveDict`
    — when a third HTTP/1.1-aware consumer arrives and we factor a
    shared ``chumicro-http`` package out (Decision 0040 §Consequences,
    Decision 0041 §Consequences), this copy retires.  Until then,
    copy-don't-couple.
    """

    def __init__(self):
        self._entries = {}

    def __setitem__(self, name, value):
        self._entries[name.lower()] = (name, value)

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


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------


def parse_ws_url(url: str) -> tuple[str, str, int, str]:
    """Split a ``ws://`` / ``wss://`` *url* into ``(scheme, host, port, path)``.

    Args:
        url: WebSocket URL.  Examples::

            ws://example.com/      -> ("ws", "example.com", 80, "/")
            wss://api.host:8443/v1 -> ("wss", "api.host", 8443, "/v1")
            ws://h/p?q=1           -> ("ws", "h", 80, "/p?q=1")

    Returns:
        4-tuple ``(scheme, host, port, path)``.  *path* always starts
        with ``/`` and includes the query string if present.

    Raises:
        WebSocketURLError: Scheme is not ``ws`` / ``wss``, host is
            missing, or port is not a base-10 integer in 1-65535.
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
    """Generate a fresh ``Sec-WebSocket-Key`` per RFC 6455 §4.1.

    16 random bytes, base64-encoded, returned as ASCII ``str``.

    Returns:
        Base64 ``str`` suitable for the ``Sec-WebSocket-Key`` header.
    """
    nonce = os.urandom(16)
    encoded = binascii.b2a_base64(nonce)
    # b2a_base64 appends a trailing newline byte.
    return encoded.rstrip(b"\n").rstrip(b"\r").decode("ascii")


def derive_accept_key(client_key: str) -> str:
    """Compute ``Sec-WebSocket-Accept`` from the client's nonce.

    Per RFC 6455 §4.2.2: ``base64(sha1(client_key + WS_MAGIC_GUID))``.

    Args:
        client_key: The ``Sec-WebSocket-Key`` header value verbatim
            (already base64-encoded; do not decode first).

    Returns:
        Base64 ``str`` to put in the server's ``Sec-WebSocket-Accept``
        header.
    """
    digest = hashlib.sha1((client_key + WS_MAGIC_GUID).encode("ascii")).digest()
    encoded = binascii.b2a_base64(digest)
    return encoded.rstrip(b"\n").rstrip(b"\r").decode("ascii")


# ---------------------------------------------------------------------------
# Handshake encoders
# ---------------------------------------------------------------------------


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
        host: Hostname for the ``Host:`` header.  No port suffix.
        port: TCP port; appended to ``Host:`` only when non-default
            (80 for ``ws://``, 443 for ``wss://``).  The transport
            decides which based on the URL scheme — pass either.
        path: Request-target — typically the URL path + query.
        key: Pre-generated nonce from :func:`make_websocket_key`.
        extra_headers: Optional iterable of ``(name, value)`` pairs,
            a ``dict``, or a :class:`CaseInsensitiveDict` to merge in
            after the required upgrade headers.  Caller-supplied headers
            override defaults; the four mandatory upgrade headers
            (``Host``, ``Upgrade``, ``Connection``, ``Sec-WebSocket-Key``,
            ``Sec-WebSocket-Version``) are always re-applied at the end
            so callers can't accidentally break the handshake.

    Returns:
        Encoded request as ``bytes``.
    """
    is_default_port = port in (80, 443)
    host_value = host if is_default_port else f"{host}:{port}"

    merged = CaseInsensitiveDict()
    if extra_headers is not None:
        if isinstance(extra_headers, CaseInsensitiveDict):
            iterable = extra_headers.items()
        elif isinstance(extra_headers, dict):
            iterable = extra_headers.items()
        else:
            iterable = extra_headers
        for header_name, header_value in iterable:
            merged[header_name] = header_value
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

    Args:
        client_key: The verbatim ``Sec-WebSocket-Key`` value the
            client sent; used to derive the accept token.
        extra_headers: Optional iterable / ``dict`` /
            :class:`CaseInsensitiveDict` to include after the
            mandatory upgrade headers.  Cannot override the
            four mandatory headers (``Upgrade``, ``Connection``,
            ``Sec-WebSocket-Accept``, status line).

    Returns:
        Encoded response as ``bytes``.
    """
    accept_token = derive_accept_key(client_key)

    merged = CaseInsensitiveDict()
    if extra_headers is not None:
        if isinstance(extra_headers, CaseInsensitiveDict):
            iterable = extra_headers.items()
        elif isinstance(extra_headers, dict):
            iterable = extra_headers.items()
        else:
            iterable = extra_headers
        for header_name, header_value in iterable:
            merged[header_name] = header_value
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
    """Encode an HTTP/1.1 error response for a rejected WS upgrade.

    Used when the client's request didn't pass the upgrade checks
    (wrong path, missing required header, unsupported version, etc.)
    so the server should answer with a regular HTTP error rather than
    a ``101``.  The connection is then closed.

    Args:
        status_code: HTTP status code (e.g. ``400``, ``404``, ``426``).
        reason_phrase: Reason text after the status code.
        body: Optional body bytes.  ``Content-Length`` is auto-added
            when set.
        content_type: ``Content-Type`` header value when *body* is set.

    Returns:
        Encoded response as ``bytes``.
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


class HandshakeResponseParser:
    """Streaming parser for the server's HTTP/1.1 ``101`` response.

    The websocket client feeds raw bytes via :meth:`feed`; the parser
    extracts status line + headers and validates the four upgrade
    invariants:

    1. Status code is ``101``.
    2. ``Upgrade:`` (case-insensitive) contains ``websocket``.
    3. ``Connection:`` (case-insensitive, comma-separated) contains
       ``upgrade``.
    4. ``Sec-WebSocket-Accept`` matches the value derived from the
       client's nonce via :func:`derive_accept_key`.

    Body bytes (if any — the ``101`` response should have none) sit
    in :attr:`leftover` for the caller to feed into the frame parser.

    Args:
        expected_accept: The accept token the client expects, derived
            from the nonce it sent.  Validation #4 compares against
            this verbatim.
        max_header_bytes: Cap on the buffered handshake to bound heap.
            Default ``8192`` — a real websocket response is well under
            this; if a peer sends more, raise rather than grow.
    """

    def __init__(self, expected_accept: str, *, max_header_bytes: int = 8192):
        self._expected_accept = expected_accept
        self._max_header_bytes = max_header_bytes
        self._buffer = bytearray()
        self._state = HandshakeParseState.STATUS_LINE
        self._status_code = None
        self._reason = ""
        self._http_version = ""
        self._headers = CaseInsensitiveDict()
        self._error = None
        self._leftover = b""

    @property
    def state(self):
        """Current :class:`HandshakeParseState`."""
        return self._state

    @property
    def status_code(self):
        """Parsed status code (e.g. ``101``), or ``None`` until parsed."""
        return self._status_code

    @property
    def reason(self):
        """Parsed reason phrase, or ``""`` until parsed."""
        return self._reason

    @property
    def http_version(self):
        """Parsed HTTP version (e.g. ``"HTTP/1.1"``), or ``""``."""
        return self._http_version

    @property
    def headers(self):
        """Parsed headers as a :class:`CaseInsensitiveDict`."""
        return self._headers

    @property
    def error(self):
        """Last parse error if :attr:`state` == ``ERROR``."""
        return self._error

    @property
    def leftover(self):
        """Bytes consumed past the header terminator.

        Empty until :attr:`state` == ``DONE``.  When non-empty,
        these are the first bytes of the websocket framing stream
        — the caller hands them straight to :class:`FrameParser`.
        """
        return self._leftover

    def feed(self, chunk: bytes) -> None:
        """Consume *chunk* bytes; advance state if possible.

        Raises:
            WebSocketHandshakeError: Buffer would exceed ``max_header_bytes``,
                status line is malformed, status is not ``101``, a
                required upgrade header is missing or wrong, or
                ``Sec-WebSocket-Accept`` doesn't match.  The parser
                also transitions to ``ERROR`` and stores the message
                in :attr:`error`.
        """
        if self._state in (HandshakeParseState.DONE, HandshakeParseState.ERROR):
            return
        self._buffer.extend(chunk)
        if len(self._buffer) > self._max_header_bytes:
            raise self._fail(
                f"handshake exceeded max_header_bytes={self._max_header_bytes}",
            )

        while True:
            terminator_index = self._buffer.find(CRLF)
            if terminator_index == -1:
                return
            line = bytes(self._buffer[:terminator_index])
            del self._buffer[: terminator_index + 2]

            if self._state == HandshakeParseState.STATUS_LINE:
                self._parse_status_line(line)
            elif self._state == HandshakeParseState.HEADERS:
                if not line:
                    self._finalize()
                    return
                self._parse_header_line(line)

    def _parse_status_line(self, line: bytes) -> None:
        try:
            decoded = line.decode("ascii")
        except UnicodeDecodeError as decode_error:
            raise self._fail(
                f"non-ASCII bytes in status line: {decode_error}",
            ) from decode_error
        # "HTTP/1.1 101 Switching Protocols" — split on first two spaces.
        parts = decoded.split(" ", 2)
        if len(parts) < 2:
            raise self._fail(f"malformed status line: {decoded!r}")
        self._http_version = parts[0]
        try:
            self._status_code = int(parts[1])
        except ValueError as parse_error:
            raise self._fail(
                f"non-integer status code: {decoded!r}",
            ) from parse_error
        self._reason = parts[2] if len(parts) == 3 else ""
        if self._status_code != 101:
            raise self._fail(
                f"server did not switch protocols: {self._status_code} "
                f"{self._reason}",
            )
        self._state = HandshakeParseState.HEADERS

    def _parse_header_line(self, line: bytes) -> None:
        decoded = line.decode("iso-8859-1")
        colon_index = decoded.find(":")
        if colon_index == -1:
            raise self._fail(f"header line missing colon: {decoded!r}")
        header_name = decoded[:colon_index].strip()
        header_value = decoded[colon_index + 1:].strip()
        if not header_name:
            raise self._fail(f"empty header name in {decoded!r}")
        self._headers[header_name] = header_value

    def _finalize(self) -> None:
        upgrade = self._headers.get("Upgrade", "").lower()
        if "websocket" not in upgrade:
            raise self._fail(
                f"server response missing 'Upgrade: websocket' "
                f"(got {upgrade!r})",
            )
        connection = self._headers.get("Connection", "").lower()
        connection_tokens = {token.strip() for token in connection.split(",")}
        if "upgrade" not in connection_tokens:
            raise self._fail(
                f"server response missing 'Connection: Upgrade' "
                f"(got {connection!r})",
            )
        accept = self._headers.get("Sec-WebSocket-Accept", "")
        if accept != self._expected_accept:
            raise self._fail(
                f"Sec-WebSocket-Accept mismatch: expected "
                f"{self._expected_accept!r}, got {accept!r}",
            )
        self._leftover = bytes(self._buffer)
        self._buffer = bytearray()
        self._state = HandshakeParseState.DONE

    def _fail(self, message: str) -> WebSocketHandshakeError:
        self._error = message
        self._state = HandshakeParseState.ERROR
        return WebSocketHandshakeError(message)


class HandshakeRequestParser:
    """Streaming parser for the client's HTTP/1.1 upgrade request.

    The websocket server feeds raw bytes via :meth:`feed`; the
    parser extracts request line + headers and validates the
    upgrade invariants:

    1. Method is ``GET``.
    2. HTTP version is ``HTTP/1.1`` or higher (``HTTP/2`` doesn't
       speak this handshake; reject with 400 in the caller).
    3. ``Upgrade:`` (case-insensitive) contains ``websocket``.
    4. ``Connection:`` (case-insensitive, comma-separated) contains
       ``upgrade``.
    5. ``Sec-WebSocket-Version`` is ``13``.
    6. ``Sec-WebSocket-Key`` is present and base64-decodes to 16
       bytes.

    Args:
        max_header_bytes: Cap on the buffered request to bound heap.
            Default ``8192``.

    Properties accessible after :attr:`state` == ``DONE``:

    * :attr:`method`, :attr:`path`, :attr:`http_version`
    * :attr:`headers`
    * :attr:`client_key` — the ``Sec-WebSocket-Key`` value verbatim
      (caller hands to :func:`derive_accept_key`).
    """

    def __init__(self, *, max_header_bytes: int = 8192):
        self._max_header_bytes = max_header_bytes
        self._buffer = bytearray()
        self._state = HandshakeParseState.REQUEST_LINE
        self._method = ""
        self._path = ""
        self._http_version = ""
        self._headers = CaseInsensitiveDict()
        self._error = None
        self._leftover = b""

    @property
    def state(self):
        """Current :class:`HandshakeParseState`."""
        return self._state

    @property
    def method(self):
        """Parsed method (``"GET"``), or ``""`` until parsed."""
        return self._method

    @property
    def path(self):
        """Parsed request-target, or ``""`` until parsed."""
        return self._path

    @property
    def http_version(self):
        """Parsed HTTP version, or ``""``."""
        return self._http_version

    @property
    def headers(self):
        """Parsed headers as a :class:`CaseInsensitiveDict`."""
        return self._headers

    @property
    def client_key(self):
        """Verbatim ``Sec-WebSocket-Key`` once headers parse, else ``""``."""
        return self._headers.get("Sec-WebSocket-Key", "")

    @property
    def error(self):
        """Last parse error if :attr:`state` == ``ERROR``."""
        return self._error

    @property
    def leftover(self):
        """Bytes consumed past the request terminator.

        Empty until :attr:`state` == ``DONE``.  These are the first
        bytes of the websocket framing stream from the client.
        """
        return self._leftover

    def feed(self, chunk: bytes) -> None:
        """Consume *chunk* bytes; advance state if possible.

        Raises:
            WebSocketHandshakeError: Buffer would exceed ``max_header_bytes``,
                request line is malformed, method is not ``GET``, or a
                required upgrade header is missing / wrong / unparseable.
        """
        if self._state in (HandshakeParseState.DONE, HandshakeParseState.ERROR):
            return
        self._buffer.extend(chunk)
        if len(self._buffer) > self._max_header_bytes:
            raise self._fail(
                f"handshake exceeded max_header_bytes={self._max_header_bytes}",
            )

        while True:
            terminator_index = self._buffer.find(CRLF)
            if terminator_index == -1:
                return
            line = bytes(self._buffer[:terminator_index])
            del self._buffer[: terminator_index + 2]

            if self._state == HandshakeParseState.REQUEST_LINE:
                self._parse_request_line(line)
            elif self._state == HandshakeParseState.HEADERS:
                if not line:
                    self._finalize()
                    return
                self._parse_header_line(line)

    def _parse_request_line(self, line: bytes) -> None:
        try:
            decoded = line.decode("ascii")
        except UnicodeDecodeError as decode_error:
            raise self._fail(
                f"non-ASCII bytes in request line: {decode_error}",
            ) from decode_error
        parts = decoded.split(" ")
        if len(parts) != 3:
            raise self._fail(f"malformed request line: {decoded!r}")
        self._method = parts[0]
        self._path = parts[1]
        self._http_version = parts[2]
        if self._method != "GET":
            raise self._fail(f"method must be GET, got {self._method!r}")
        if not self._http_version.startswith("HTTP/1."):
            raise self._fail(
                f"unsupported HTTP version {self._http_version!r}; "
                f"must be HTTP/1.1+",
            )
        self._state = HandshakeParseState.HEADERS

    def _parse_header_line(self, line: bytes) -> None:
        decoded = line.decode("iso-8859-1")
        colon_index = decoded.find(":")
        if colon_index == -1:
            raise self._fail(f"header line missing colon: {decoded!r}")
        header_name = decoded[:colon_index].strip()
        header_value = decoded[colon_index + 1:].strip()
        if not header_name:
            raise self._fail(f"empty header name in {decoded!r}")
        self._headers[header_name] = header_value

    def _finalize(self) -> None:
        upgrade = self._headers.get("Upgrade", "").lower()
        if "websocket" not in upgrade:
            raise self._fail(
                f"client request missing 'Upgrade: websocket' "
                f"(got {upgrade!r})",
            )
        connection = self._headers.get("Connection", "").lower()
        connection_tokens = {token.strip() for token in connection.split(",")}
        if "upgrade" not in connection_tokens:
            raise self._fail(
                f"client request missing 'Connection: Upgrade' "
                f"(got {connection!r})",
            )
        version = self._headers.get("Sec-WebSocket-Version", "")
        if version != WS_VERSION:
            raise self._fail(
                f"unsupported Sec-WebSocket-Version {version!r}; "
                f"must be {WS_VERSION!r}",
            )
        key = self._headers.get("Sec-WebSocket-Key", "")
        if not key:
            raise self._fail("client request missing Sec-WebSocket-Key")
        try:
            decoded_key = binascii.a2b_base64(key.encode("ascii"))
        except (binascii.Error, ValueError) as decode_error:
            raise self._fail(
                f"Sec-WebSocket-Key is not valid base64: {decode_error}",
            ) from decode_error
        if len(decoded_key) != 16:
            raise self._fail(
                f"Sec-WebSocket-Key must decode to 16 bytes, got "
                f"{len(decoded_key)}",
            )
        self._leftover = bytes(self._buffer)
        self._buffer = bytearray()
        self._state = HandshakeParseState.DONE

    def _fail(self, message: str) -> WebSocketHandshakeError:
        self._error = message
        self._state = HandshakeParseState.ERROR
        return WebSocketHandshakeError(message)


# ---------------------------------------------------------------------------
# Frame parsing
# ---------------------------------------------------------------------------


class FrameParseState:
    """Streaming binary-frame parser states.

    One frame at a time::

        READING_HEADER -> [READING_LEN16 | READING_LEN64]
                       -> [READING_MASK]
                       -> READING_PAYLOAD
                       -> FRAME_READY
                       \\-> ERROR (any state)

    After ``FRAME_READY``, the caller reads :attr:`fin` /
    :attr:`opcode` / :attr:`payload`, then calls :meth:`reset` to
    return to ``READING_HEADER`` for the next frame.
    """

    READING_HEADER = "reading_header"
    READING_LEN16 = "reading_len16"
    READING_LEN64 = "reading_len64"
    READING_MASK = "reading_mask"
    READING_PAYLOAD = "reading_payload"
    FRAME_READY = "frame_ready"
    ERROR = "error"


class FrameParser:
    """Streaming RFC 6455 §5 binary-frame parser.

    One frame at a time — the higher layers (client / server) handle
    fragmentation reassembly, control-frame routing, mask-direction
    policy, and UTF-8 validation.

    Args:
        max_payload_bytes: Per-frame payload cap.  Lengths above this
            transition the parser to ``ERROR`` at the length-byte
            stage (i.e. before any payload bytes get buffered) so a
            hostile peer can't pin heap with a 64-bit length header.

    Public state on :attr:`state` == ``FRAME_READY``:

    * :attr:`fin`        — bool, FIN bit
    * :attr:`rsv`        — int, three RSV bits packed (RSV1<<2|RSV2<<1|RSV3)
    * :attr:`opcode`     — int (one of ``OPCODE_*``)
    * :attr:`had_mask`   — bool (was MASK bit set?)
    * :attr:`payload`    — ``bytes`` of unmasked payload
    """

    def __init__(self, *, max_payload_bytes: int = DEFAULT_MAX_MESSAGE_BYTES):
        self._max_payload_bytes = max_payload_bytes
        self._state = FrameParseState.READING_HEADER
        self._buffer = bytearray()
        self._fin = False
        self._rsv = 0
        self._opcode = 0
        self._had_mask = False
        self._payload_length = 0
        self._mask_key = b""
        self._payload = bytearray()
        self._error = None

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------

    @property
    def state(self):
        """Current :class:`FrameParseState`."""
        return self._state

    @property
    def fin(self):
        """``FIN`` bit of the in-flight or just-completed frame."""
        return self._fin

    @property
    def rsv(self):
        """Packed RSV bits (RSV1<<2 | RSV2<<1 | RSV3); usually 0."""
        return self._rsv

    @property
    def opcode(self):
        """Opcode of the in-flight or just-completed frame (0-15)."""
        return self._opcode

    @property
    def had_mask(self):
        """Whether the inbound frame had the ``MASK`` bit set."""
        return self._had_mask

    @property
    def payload(self):
        """Unmasked payload of the just-completed frame as ``bytes``.

        Returns ``b""`` until :attr:`state` == ``FRAME_READY``.
        """
        return bytes(self._payload)

    @property
    def error(self):
        """Last parse error if :attr:`state` == ``ERROR``."""
        return self._error

    # ------------------------------------------------------------------
    # Driving
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Return to ``READING_HEADER`` for the next frame.

        Discards the just-finished frame's metadata + payload.
        """
        self._state = FrameParseState.READING_HEADER
        self._buffer = bytearray()
        self._fin = False
        self._rsv = 0
        self._opcode = 0
        self._had_mask = False
        self._payload_length = 0
        self._mask_key = b""
        self._payload = bytearray()

    def feed(self, chunk: bytes) -> int:
        """Consume bytes from *chunk*; return how many were used.

        The parser stops consuming when it transitions to
        ``FRAME_READY`` so any leftover bytes remain available to
        the caller for the next frame.

        Raises:
            WebSocketProtocolError: Reserved opcode, control frame
                with payload >125, control frame with FIN=0, or
                payload length exceeds ``max_payload_bytes``.
                The parser also transitions to ``ERROR`` and stores
                the message in :attr:`error`.
        """
        consumed = 0
        chunk_length = len(chunk)
        while consumed < chunk_length and self._state not in (
            FrameParseState.FRAME_READY,
            FrameParseState.ERROR,
        ):
            self._step(chunk[consumed])
            consumed += 1
        return consumed

    def _step(self, byte_value: int) -> None:
        """Consume a single byte and update state in place.

        Raises:
            WebSocketProtocolError: Reserved opcode, control frame
                with FIN=0, control frame with payload >125, or
                payload length exceeds ``max_payload_bytes``.
        """
        if self._state == FrameParseState.READING_HEADER:
            self._buffer.append(byte_value)
            if len(self._buffer) >= 2:
                self._dispatch_header()
            return
        if self._state == FrameParseState.READING_LEN16:
            self._buffer.append(byte_value)
            if len(self._buffer) >= 2:
                self._payload_length = struct.unpack("!H", bytes(self._buffer))[0]
                self._buffer = bytearray()
                self._after_length()
            return
        if self._state == FrameParseState.READING_LEN64:
            self._buffer.append(byte_value)
            if len(self._buffer) >= 8:
                self._payload_length = struct.unpack("!Q", bytes(self._buffer))[0]
                self._buffer = bytearray()
                self._after_length()
            return
        if self._state == FrameParseState.READING_MASK:
            self._buffer.append(byte_value)
            if len(self._buffer) >= 4:
                self._mask_key = bytes(self._buffer)
                self._buffer = bytearray()
                self._after_mask()
            return
        if self._state == FrameParseState.READING_PAYLOAD:
            if self._had_mask:
                mask_byte = self._mask_key[len(self._payload) & 3]
                self._payload.append(byte_value ^ mask_byte)
            else:
                self._payload.append(byte_value)
            if len(self._payload) >= self._payload_length:
                self._state = FrameParseState.FRAME_READY
            return

    def _dispatch_header(self) -> None:
        first_byte = self._buffer[0]
        second_byte = self._buffer[1]
        self._fin = bool(first_byte & 0x80)
        self._rsv = (first_byte >> 4) & 0x07
        self._opcode = first_byte & 0x0F
        self._had_mask = bool(second_byte & 0x80)
        length_marker = second_byte & 0x7F

        if self._rsv != 0:
            raise self._fail(
                f"non-zero RSV bits {self._rsv:03b} (no extensions negotiated)",
            )
        if self._opcode in CONTROL_OPCODES:
            if not self._fin:
                raise self._fail(
                    f"control frame opcode 0x{self._opcode:x} must be FIN=1",
                )
        elif self._opcode not in DATA_OPCODES:
            raise self._fail(f"reserved opcode 0x{self._opcode:x}")

        self._buffer = bytearray()
        if length_marker < 126:
            self._payload_length = length_marker
            self._after_length()
            return
        if length_marker == 126:
            self._state = FrameParseState.READING_LEN16
            return
        # length_marker == 127
        self._state = FrameParseState.READING_LEN64

    def _after_length(self) -> None:
        if self._opcode in CONTROL_OPCODES and self._payload_length > MAX_CONTROL_PAYLOAD_BYTES:
            raise self._fail(
                f"control frame opcode 0x{self._opcode:x} payload "
                f"{self._payload_length} > {MAX_CONTROL_PAYLOAD_BYTES}",
            )
        if self._payload_length > self._max_payload_bytes:
            raise self._fail(
                f"frame payload {self._payload_length} > "
                f"max_payload_bytes={self._max_payload_bytes}",
            )
        if self._had_mask:
            self._state = FrameParseState.READING_MASK
            return
        self._after_mask()

    def _after_mask(self) -> None:
        if self._payload_length == 0:
            self._state = FrameParseState.FRAME_READY
            return
        self._state = FrameParseState.READING_PAYLOAD

    def _fail(self, message: str) -> WebSocketProtocolError:
        self._error = message
        self._state = FrameParseState.ERROR
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
            ``True`` in v1 outbound (Decision 0045 §9 — no outbound
            fragmentation).  Exposed for tests.
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
        parts.extend(struct.pack("!H", payload_length))
    else:
        parts.append(mask_bit | 127)
        parts.extend(struct.pack("!Q", payload_length))
    if mask is not None:
        parts.extend(mask)
        masked = bytearray(payload_length)
        for index in range(payload_length):
            masked[index] = payload[index] ^ mask[index & 3]
        parts.extend(masked)
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
    return struct.pack("!H", code) + encoded_reason


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
    code = struct.unpack("!H", bytes(payload[:2]))[0]
    if code in RESERVED_CLOSE_CODES:
        raise WebSocketProtocolError(
            f"peer sent reserved close code {code}",
        )
    try:
        reason = bytes(payload[2:]).decode("utf-8")
    except UnicodeDecodeError as decode_error:
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
        return bytes(payload).decode("utf-8")
    except UnicodeDecodeError as decode_error:
        raise WebSocketProtocolError(
            f"text payload is not valid UTF-8: {decode_error}",
        ) from decode_error
