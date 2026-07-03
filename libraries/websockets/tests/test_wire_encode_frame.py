"""Wire tests for chumicro_websockets._wire: encode_frame and
encode_close_payload."""

import struct

from chumicro_test_harness import skip
from chumicro_test_harness.assertions import raises
from chumicro_websockets import (
    CLOSE_NORMAL,
    OPCODE_BINARY,
    OPCODE_PING,
    OPCODE_TEXT,
    WebSocketProtocolError,
)
from chumicro_websockets._wire import (
    CLOSE_ABNORMAL,
    FrameParser,
    encode_close_payload,
    encode_frame,
    make_mask_key,
)


class TestEncodeFrame:
    """Outbound frame encoder matches the byte layout the parser expects."""

    def test_unmasked_short_text(self):
        encoded = encode_frame(OPCODE_TEXT, b"hello")
        assert encoded == b"\x81\x05hello"

    def test_masked_short_text_round_trip(self):
        mask = b"mask"
        encoded = encode_frame(OPCODE_TEXT, b"hello", mask=mask)
        # Header: \x81 (FIN+TEXT), \x85 (MASK + len 5), then mask, then masked payload.
        assert encoded[:2] == b"\x81\x85"
        assert encoded[2:6] == mask
        # Round-trip via parser.
        parser = FrameParser()
        parser.feed(encoded)
        assert parser.payload == b"hello"

    def test_unmasked_16bit_length(self):
        payload = b"X" * 200
        encoded = encode_frame(OPCODE_BINARY, payload)
        assert encoded[:2] == b"\x82\x7e"
        assert struct.unpack("!H", encoded[2:4])[0] == 200
        assert encoded[4:] == payload

    def test_unmasked_64bit_length(self):
        # The 64-bit length prefix only triggers at payloads >= 65536
        # bytes (4x the library's 16 KB DEFAULT_MAX_MESSAGE_BYTES).  The
        # ~64 KB payload plus its encoded copy exceeds a 264 KB board's
        # contiguous-allocation headroom.  This is an intrinsic single
        # allocation, not the resident co-residency a file split fixes,
        # so it is loud-skipped on the constrained tier and validated on
        # PSRAM + CPython instead.
        try:
            import gc

            free = gc.mem_free()
        except (ImportError, AttributeError):
            free = None  # CPython has no gc.mem_free — run the test.
        if free is not None and free < 200_000:
            skip(
                "64-bit frame-length path needs ~64 KB+ contiguous; "
                "exceeds 264 KB-board headroom (intrinsic allocation, "
                "not co-residency a split fixes); validated on PSRAM "
                "+ CPython",
            )
        payload = b"Y" * (1 << 16)
        encoded = encode_frame(OPCODE_BINARY, payload)
        assert encoded[:2] == b"\x82\x7f"
        assert struct.unpack("!Q", encoded[2:10])[0] == (1 << 16)

    def test_fin_zero_clears_high_bit(self):
        encoded = encode_frame(OPCODE_TEXT, b"hi", fin=False)
        assert encoded[0] == OPCODE_TEXT  # high bit cleared

    def test_control_frame_oversize_raises(self):
        with raises(WebSocketProtocolError, match="125"):
            encode_frame(OPCODE_PING, b"X" * 126)

    def test_invalid_mask_length_raises(self):
        with raises(WebSocketProtocolError, match="mask"):
            encode_frame(OPCODE_TEXT, b"hi", mask=b"abc")

    def test_empty_payload_unmasked(self):
        encoded = encode_frame(OPCODE_PING, b"")
        assert encoded == b"\x89\x00"

    def test_empty_payload_masked(self):
        encoded = encode_frame(OPCODE_PING, b"", mask=b"mask")
        # Empty payload still includes mask bytes.
        assert encoded == b"\x89\x80mask"

    def test_returns_bytearray_for_zero_copy_send(self):
        # encode_frame returns its working bytearray directly rather than
        # a bytes() snapshot; socket.send accepts a bytearray buffer, so
        # the send path skips a full-frame copy.
        encoded = encode_frame(OPCODE_TEXT, b"hi")
        assert isinstance(encoded, bytearray)

    def test_make_mask_key_length(self):
        assert len(make_mask_key()) == 4
        # Non-deterministic, but two calls almost surely differ.
        assert make_mask_key() != make_mask_key()


class TestEncodeClosePayload:
    """Close-frame body encoder."""

    def test_empty_close_no_code(self):
        assert encode_close_payload(None) == b""

    def test_reason_without_code_raises(self):
        with raises(WebSocketProtocolError, match="without a code"):
            encode_close_payload(None, "bye")

    def test_normal_close_with_reason(self):
        encoded = encode_close_payload(CLOSE_NORMAL, "bye")
        assert encoded[:2] == struct.pack("!H", CLOSE_NORMAL)
        assert encoded[2:] == b"bye"

    def test_reserved_code_rejected(self):
        with raises(WebSocketProtocolError, match="reserved"):
            encode_close_payload(CLOSE_ABNORMAL, "")

    def test_oversize_reason_rejected(self):
        with raises(WebSocketProtocolError, match="125"):
            encode_close_payload(CLOSE_NORMAL, "X" * 200)
