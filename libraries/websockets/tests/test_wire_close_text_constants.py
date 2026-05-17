"""Wire tests for chumicro_websockets._wire: parse_close_payload,
validate_text_payload, module constants."""

import struct

from chumicro_test_harness.assertions import raises
from chumicro_websockets import (
    CLOSE_BAD_DATA,
    CLOSE_GOING_AWAY,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_CONTINUATION,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    WebSocketProtocolError,
    WebSocketState,
)
from chumicro_websockets._wire import (
    CLOSE_ABNORMAL,
    DEFAULT_MAX_MESSAGE_BYTES,
    MAX_CONTROL_PAYLOAD_BYTES,
    WS_VERSION,
    parse_close_payload,
    validate_text_payload,
)


class TestParseClosePayload:
    """Close-frame body decoder."""

    def test_empty_payload(self):
        assert parse_close_payload(b"") == (None, "")

    def test_one_byte_payload_rejected(self):
        with raises(WebSocketProtocolError, match="1 byte"):
            parse_close_payload(b"\x03")

    def test_code_and_reason(self):
        body = struct.pack("!H", CLOSE_GOING_AWAY) + b"bye"
        assert parse_close_payload(body) == (CLOSE_GOING_AWAY, "bye")

    def test_code_only(self):
        body = struct.pack("!H", CLOSE_NORMAL)
        assert parse_close_payload(body) == (CLOSE_NORMAL, "")

    def test_reserved_code_rejected(self):
        body = struct.pack("!H", CLOSE_ABNORMAL)
        with raises(WebSocketProtocolError, match="reserved"):
            parse_close_payload(body)

    def test_invalid_utf8_reason_rejected(self):
        body = struct.pack("!H", CLOSE_NORMAL) + b"\xff\xfe"
        with raises(WebSocketProtocolError, match="UTF-8"):
            parse_close_payload(body)


class TestValidateTextPayload:
    """RFC 6455 §8.1 — text frames MUST be valid UTF-8."""

    def test_ascii_passes(self):
        assert validate_text_payload(b"hello") == "hello"

    def test_multibyte_utf8_passes(self):
        # Snowman, 3 bytes UTF-8.
        assert validate_text_payload(b"\xe2\x98\x83") == "☃"

    def test_invalid_utf8_raises(self):
        with raises(WebSocketProtocolError, match="UTF-8"):
            validate_text_payload(b"\xff\xfe")


class TestConstants:
    """Constant values match spec."""

    def test_ws_version(self):
        assert WS_VERSION == "13"

    def test_max_control_payload(self):
        assert MAX_CONTROL_PAYLOAD_BYTES == 125

    def test_default_max_message_bytes(self):
        assert DEFAULT_MAX_MESSAGE_BYTES == 16384

    def test_close_codes(self):
        assert CLOSE_NORMAL == 1000
        assert CLOSE_PROTOCOL_ERROR == 1002
        assert CLOSE_BAD_DATA == 1007

    def test_state_constants(self):
        assert WebSocketState.CONNECTING == "connecting"
        assert WebSocketState.OPEN == "open"
        assert WebSocketState.CLOSING == "closing"
        assert WebSocketState.CLOSED == "closed"

    def test_opcode_categories(self):
        from chumicro_websockets._wire import CONTROL_OPCODES, DATA_OPCODES

        assert OPCODE_TEXT in DATA_OPCODES
        assert OPCODE_BINARY in DATA_OPCODES
        assert OPCODE_CONTINUATION in DATA_OPCODES
        assert OPCODE_PING in CONTROL_OPCODES
        assert OPCODE_PONG in CONTROL_OPCODES
        assert OPCODE_CLOSE in CONTROL_OPCODES
