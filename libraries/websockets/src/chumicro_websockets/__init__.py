"""Non-blocking WebSocket client + server for CircuitPython, MicroPython, and CPython.

Built on :mod:`chumicro_sockets` (TCP + TLS) and :mod:`chumicro_timing`
(ticks).  No async, no threads — Decision 0014's runner pattern:
both :class:`WebSocketClient` and :class:`WebSocketServer` satisfy
``check(now_ms) -> bool`` + ``handle(now_ms)``.  The canonical
promise (Decision 0045): an LED can keep blinking on the same board
through the opening handshake, frame I/O, control-frame interleave,
and the close handshake.

Public API::

    from chumicro_websockets import WebSocketClient, WebSocketState

    def make_socket(host, port, use_tls):
        from chumicro_sockets import tcp_client_socket
        return tcp_client_socket(host, port)

    client = WebSocketClient(connection_factory=make_socket)
    client.on_text = lambda text: print(text)
    client.connect("ws://api.example.com/stream")

    while client.state != WebSocketState.CLOSED:
        if client.check(now_ms()):
            client.handle(now_ms())

Slices shipped (Decision 0045 §12):

* **Slice 1** — ``_wire`` layer (URL parser, handshake encoders +
  parsers, :class:`FrameParser`, :func:`encode_frame`, close-payload
  codec, exception hierarchy).
* **Slice 2** (this commit) — :class:`WebSocketClient` runner-shaped
  client + :class:`WhenOversized` policy.

Coming up:

* **Slice 3** — :class:`WebSocketServer`.
* **Slice 4** — ``chumicro_websockets.testing`` fakes
  (``FakeConnection`` / ``FakeListener``).
* **Slice 5** — ``chumicro_websockets.sockets_factory`` helper +
  README + ``docs/guide.md`` polish + examples per Decision 0042
  Class 1 sub-rule.
* **Slice 6** — live-board functional tests against a host CPython
  ``websockets`` PyPI server.
"""

from chumicro_websockets._wire import (
    CLOSE_ABNORMAL,
    CLOSE_BAD_DATA,
    CLOSE_GOING_AWAY,
    CLOSE_INTERNAL_ERROR,
    CLOSE_MISSING_EXTN,
    CLOSE_NO_STATUS_RCVD,
    CLOSE_NORMAL,
    CLOSE_POLICY_VIOLATION,
    CLOSE_PROTOCOL_ERROR,
    CLOSE_TLS_HANDSHAKE,
    CLOSE_TOO_BIG,
    CLOSE_UNSUPPORTED_DATA,
    CONTROL_OPCODES,
    DATA_OPCODES,
    DEFAULT_CLOSE_TIMEOUT_MS,
    DEFAULT_HANDSHAKE_TIMEOUT_MS,
    DEFAULT_MAX_MESSAGE_BYTES,
    DEFAULT_MAX_TX_QUEUE_SIZE,
    DEFAULT_PONG_TIMEOUT_MS,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_SEND_BUDGET_PER_TICK,
    MAX_CONTROL_PAYLOAD_BYTES,
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_CONTINUATION,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    RESERVED_CLOSE_CODES,
    WS_MAGIC_GUID,
    WS_VERSION,
    CaseInsensitiveDict,
    FrameParser,
    FrameParseState,
    HandshakeParseState,
    HandshakeRequestParser,
    HandshakeResponseParser,
    WebSocketBackpressureError,
    WebSocketError,
    WebSocketHandshakeError,
    WebSocketOversizedError,
    WebSocketProtocolError,
    WebSocketState,
    WebSocketStateError,
    WebSocketTimeoutError,
    WebSocketURLError,
    derive_accept_key,
    encode_client_handshake,
    encode_close_payload,
    encode_frame,
    encode_server_handshake_response,
    encode_server_rejection,
    make_mask_key,
    make_websocket_key,
    parse_close_payload,
    parse_ws_url,
    validate_text_payload,
)
from chumicro_websockets.client import (
    ConnectingPhase,
    WebSocketClient,
    WhenOversized,
)

__all__ = [
    "CLOSE_ABNORMAL",
    "CLOSE_BAD_DATA",
    "CLOSE_GOING_AWAY",
    "CLOSE_INTERNAL_ERROR",
    "CLOSE_MISSING_EXTN",
    "CLOSE_NO_STATUS_RCVD",
    "CLOSE_NORMAL",
    "CLOSE_POLICY_VIOLATION",
    "CLOSE_PROTOCOL_ERROR",
    "CLOSE_TLS_HANDSHAKE",
    "CLOSE_TOO_BIG",
    "CLOSE_UNSUPPORTED_DATA",
    "CONTROL_OPCODES",
    "DATA_OPCODES",
    "DEFAULT_CLOSE_TIMEOUT_MS",
    "DEFAULT_HANDSHAKE_TIMEOUT_MS",
    "DEFAULT_MAX_MESSAGE_BYTES",
    "DEFAULT_MAX_TX_QUEUE_SIZE",
    "DEFAULT_PONG_TIMEOUT_MS",
    "DEFAULT_RECV_BUDGET_PER_TICK",
    "DEFAULT_SEND_BUDGET_PER_TICK",
    "MAX_CONTROL_PAYLOAD_BYTES",
    "OPCODE_BINARY",
    "OPCODE_CLOSE",
    "OPCODE_CONTINUATION",
    "OPCODE_PING",
    "OPCODE_PONG",
    "OPCODE_TEXT",
    "RESERVED_CLOSE_CODES",
    "WS_MAGIC_GUID",
    "WS_VERSION",
    "CaseInsensitiveDict",
    "ConnectingPhase",
    "FrameParser",
    "FrameParseState",
    "HandshakeParseState",
    "HandshakeRequestParser",
    "HandshakeResponseParser",
    "WebSocketBackpressureError",
    "WebSocketClient",
    "WebSocketError",
    "WebSocketHandshakeError",
    "WebSocketOversizedError",
    "WebSocketProtocolError",
    "WebSocketState",
    "WebSocketStateError",
    "WebSocketTimeoutError",
    "WebSocketURLError",
    "WhenOversized",
    "derive_accept_key",
    "encode_client_handshake",
    "encode_close_payload",
    "encode_frame",
    "encode_server_handshake_response",
    "encode_server_rejection",
    "make_mask_key",
    "make_websocket_key",
    "parse_close_payload",
    "parse_ws_url",
    "validate_text_payload",
]
