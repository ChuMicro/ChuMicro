"""Wire tests for chumicro_websockets._wire: FrameParser framing
math — happy path, oversize drain, parse errors."""

import struct

from chumicro_test_harness.assertions import raises
from chumicro_websockets import (
    CLOSE_NORMAL,
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_CONTINUATION,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    WebSocketProtocolError,
)
from chumicro_websockets._wire import (
    FrameParser,
    FrameParseState,
)


class TestFrameParserHappyPath:
    """Single-frame parsing across all length encodings + mask handling."""

    def test_short_unmasked_text_frame(self):
        # FIN=1, opcode=TEXT, MASK=0, len=5, payload=b"hello"
        parser = FrameParser()
        consumed = parser.feed(b"\x81\x05hello")
        assert parser.state == FrameParseState.FRAME_READY
        assert consumed == 7
        assert parser.fin is True
        assert parser.rsv == 0
        assert parser.opcode == OPCODE_TEXT
        assert parser.had_mask is False
        assert parser.payload == b"hello"

    def test_short_masked_frame_unmasks_payload(self):
        # Client to server: MASK=1, mask=b"mask", len=4, payload="ping" XOR mask.
        mask = b"mask"
        plaintext = b"ping"
        masked = bytes(plaintext[index] ^ mask[index & 3] for index in range(4))
        frame = b"\x81\x84" + mask + masked
        parser = FrameParser()
        parser.feed(frame)
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.had_mask is True
        assert parser.payload == plaintext

    def test_16bit_length_frame(self):
        # FIN=1, BINARY, MASK=0, length-marker=126, 16-bit length
        payload = b"X" * 200
        frame = b"\x82\x7e" + struct.pack("!H", 200) + payload
        parser = FrameParser()
        parser.feed(frame)
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.opcode == OPCODE_BINARY
        assert parser.payload == payload

    def test_64bit_length_frame(self):
        # Up to max_payload_bytes default 16384.  Exercise the 64-bit branch
        # with a small payload: the length-byte parsing path matters more
        # than payload size.
        payload = b"Y" * 3000
        frame = b"\x82\x7f" + struct.pack("!Q", 3000) + payload
        parser = FrameParser()
        parser.feed(frame)
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.payload == payload

    def test_zero_length_frame_reaches_ready_immediately(self):
        # Empty PING (valid: control frames may have empty payload).
        parser = FrameParser()
        parser.feed(b"\x89\x00")
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.opcode == OPCODE_PING
        assert parser.payload == b""

    def test_byte_at_a_time(self):
        frame = b"\x81\x05hello"
        parser = FrameParser()
        for byte_value in frame:
            parser.feed(bytes([byte_value]))
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.payload == b"hello"

    def test_masked_frame_with_mask_key_split_across_feeds(self):
        # A masked frame whose 4-byte mask key trickles in split 2/1/1
        # (arbitrary TCP segmentation).  The header-field completion
        # check must compare against the field's total size, not the
        # bytes-still-missing at each feed, or a 3-byte mask key is
        # accepted and the payload unmasks to garbage.
        mask = b"mask"
        plaintext = b"hi"
        masked = bytes(plaintext[index] ^ mask[index & 3] for index in range(2))
        # FIN=1, opcode=TEXT, MASK=1, len=2.
        frame = b"\x81\x82" + mask + masked
        parser = FrameParser()
        # header (2) + first 2 mask bytes, then 1, then 1 + payload.
        parser.feed(frame[0:4])
        parser.feed(frame[4:5])
        parser.feed(frame[5:6])
        parser.feed(frame[6:])
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.had_mask is True
        assert parser.payload == plaintext

    def test_64bit_length_split_across_feeds(self):
        # The 8-byte extended length split 4/4 must not complete early.
        payload = b"Z" * 400
        frame = b"\x82\x7f" + struct.pack("!Q", 400) + payload
        parser = FrameParser()
        parser.feed(frame[0:2])       # header, transition to READING_LEN64
        parser.feed(frame[2:6])       # first 4 length bytes
        parser.feed(frame[6:10])      # last 4 length bytes
        parser.feed(frame[10:])       # payload
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.reported_length == 400
        assert parser.payload == payload

    def test_consumed_count_stops_at_frame_boundary(self):
        # Feed two back-to-back frames.  First call consumes only frame 1.
        first = b"\x81\x03foo"
        second = b"\x81\x03bar"
        parser = FrameParser()
        consumed = parser.feed(first + second)
        assert consumed == len(first)
        assert parser.payload == b"foo"
        parser.reset()
        consumed = parser.feed(second)
        assert consumed == len(second)
        assert parser.payload == b"bar"

    def test_reset_clears_state(self):
        parser = FrameParser()
        parser.feed(b"\x81\x03foo")
        assert parser.state == FrameParseState.FRAME_READY
        parser.reset()
        assert parser.state == FrameParseState.READING_HEADER
        assert parser.payload == b""
        assert parser.opcode == 0

    def test_continuation_opcode_recognized(self):
        # FIN=0 + CONT is valid mid-fragmentation.  The parser doesn't
        # enforce message-level rules (that's the client/server's job).
        parser = FrameParser()
        parser.feed(b"\x00\x03foo")
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.opcode == OPCODE_CONTINUATION
        assert parser.fin is False

    def test_pong_recognized(self):
        parser = FrameParser()
        parser.feed(b"\x8a\x04pong")
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.opcode == OPCODE_PONG

    def test_close_recognized(self):
        # Close with code 1000.
        body = struct.pack("!H", CLOSE_NORMAL)
        parser = FrameParser()
        parser.feed(b"\x88\x02" + body)
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.opcode == OPCODE_CLOSE


class TestFrameParserOversizeDrain:
    """Frames declaring a length > ``max_payload_bytes`` drain through
    the parser without storing the payload.  The parser stays usable
    for the next frame, and the session layer applies its
    ``WhenOversized`` policy at message-FIN time.
    """

    def test_oversize_16bit_length_drains_payload(self):
        parser = FrameParser(max_payload_bytes=100)
        payload = b"X" * 500
        consumed = parser.feed(b"\x82\x7e" + struct.pack("!H", 500) + payload)
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.oversized is True
        assert parser.payload == b""
        assert parser.reported_length == 500
        assert consumed == 4 + 500

    def test_oversize_64bit_length_drains_payload(self):
        parser = FrameParser(max_payload_bytes=100)
        payload = b"Y" * 1000
        consumed = parser.feed(b"\x82\x7f" + struct.pack("!Q", 1000) + payload)
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.oversized is True
        assert parser.payload == b""
        assert parser.reported_length == 1000
        assert consumed == 10 + 1000

    def test_oversize_masked_frame_drains_without_unmasking(self):
        # Mask bytes still consumed off the wire, but payload bytes
        # are discarded.  XOR is skipped since the bytes are going in
        # the bin either way.
        parser = FrameParser(max_payload_bytes=100)
        mask = b"mask"
        payload = b"Z" * 500
        frame = b"\x82\xfe" + struct.pack("!H", 500) + mask + payload
        consumed = parser.feed(frame)
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.oversized is True
        assert parser.had_mask is True
        assert parser.payload == b""
        assert parser.reported_length == 500
        assert consumed == len(frame)

    def test_oversize_drain_across_feed_calls(self):
        # Tier-3 drain must hold state across short feeds.  Real TCP
        # delivers bytes in arbitrary chunks.
        parser = FrameParser(max_payload_bytes=100)
        frame = b"\x82\x7e" + struct.pack("!H", 500) + b"X" * 500
        consumed = 0
        chunk_size = 73
        for offset in range(0, len(frame), chunk_size):
            consumed += parser.feed(frame[offset : offset + chunk_size])
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.oversized is True
        assert consumed == len(frame)

    def test_reset_after_oversize_clears_state(self):
        parser = FrameParser(max_payload_bytes=100)
        parser.feed(b"\x82\x7e" + struct.pack("!H", 500) + b"X" * 500)
        assert parser.oversized is True
        parser.reset()
        assert parser.state == FrameParseState.READING_HEADER
        assert parser.oversized is False
        # Next frame parses normally.
        parser.feed(b"\x81\x05hello")
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.oversized is False
        assert parser.payload == b"hello"

    def test_oversize_frame_followed_by_normal_frame(self):
        # Two back-to-back frames in one feed call: oversized + normal.
        # `consumed` stops at the oversized frame's last byte.  Caller
        # then resets and feeds the rest.
        parser = FrameParser(max_payload_bytes=100)
        oversized = b"\x82\x7e" + struct.pack("!H", 500) + b"X" * 500
        normal = b"\x81\x05hello"
        consumed = parser.feed(oversized + normal)
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.oversized is True
        assert consumed == len(oversized)
        parser.reset()
        consumed = parser.feed(normal)
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.oversized is False
        assert parser.payload == b"hello"
        assert consumed == len(normal)

    def test_oversize_control_frame_still_raises(self):
        # RFC 6455 §5.5: control frame > 125 is a protocol error even
        # under tier-3 routing.  Connection must close with 1002.
        parser = FrameParser(max_payload_bytes=10_000)
        with raises(WebSocketProtocolError, match="125"):
            parser.feed(b"\x89\x7e" + struct.pack("!H", 200))


class TestFrameParserErrors:
    """Reserved bits, oversize, control-frame violations all raise."""

    def test_rsv_bits_set_raises(self):
        # First byte 0xc1 has RSV1 set with FIN+TEXT.
        parser = FrameParser()
        with raises(WebSocketProtocolError, match="RSV"):
            parser.feed(b"\xc1\x00")

    def test_reserved_data_opcode_raises(self):
        # Opcode 0x3 is reserved.
        parser = FrameParser()
        with raises(WebSocketProtocolError, match="reserved opcode"):
            parser.feed(b"\x83\x00")

    def test_reserved_control_opcode_raises(self):
        # Opcode 0xb is reserved control-space.
        parser = FrameParser()
        with raises(WebSocketProtocolError, match="reserved opcode"):
            parser.feed(b"\x8b\x00")

    def test_control_frame_with_fin_zero_raises(self):
        # PING (0x9) with FIN=0 is a protocol violation.
        parser = FrameParser()
        with raises(WebSocketProtocolError, match="must be FIN=1"):
            parser.feed(b"\x09\x00")

    def test_control_frame_payload_over_125_raises(self):
        # PING with 126-byte payload, which uses the 16-bit length form
        # which itself is illegal for control frames.
        parser = FrameParser()
        with raises(WebSocketProtocolError, match="125"):
            parser.feed(b"\x89\x7e" + struct.pack("!H", 126))

    def test_feed_after_error_returns_zero_consumed(self):
        parser = FrameParser()
        with raises(WebSocketProtocolError):
            parser.feed(b"\xc1\x00")
        consumed = parser.feed(b"more")
        assert consumed == 0
        assert parser.state == FrameParseState.ERROR

    def test_feed_after_ready_returns_zero_consumed(self):
        # Caller must reset() first.
        parser = FrameParser()
        parser.feed(b"\x81\x03foo")
        consumed = parser.feed(b"\x81\x03bar")
        assert consumed == 0

    def test_error_accessor_exposes_failure_reason(self):
        parser = FrameParser()
        with raises(WebSocketProtocolError):
            parser.feed(b"\xc1\x00")  # RSV bit set
        assert parser.state == FrameParseState.ERROR
        assert "RSV" in parser.error
