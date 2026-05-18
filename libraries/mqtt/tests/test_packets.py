"""Tests for the wire-format primitives."""

from chumicro_mqtt import MQTTProtocolError
from chumicro_mqtt._wire import (
    decode_varlen,
    encode_string,
    encode_varlen,
    topic_matches,
)
from chumicro_test_harness.assertions import raises


class TestEncodeVarlen:
    def test_canonical_encodings(self) -> None:
        cases = [
            (0, b"\x00"),
            (1, b"\x01"),
            (127, b"\x7f"),
            (128, b"\x80\x01"),
            (16_383, b"\xff\x7f"),
            (16_384, b"\x80\x80\x01"),
            (2_097_151, b"\xff\xff\x7f"),
            (2_097_152, b"\x80\x80\x80\x01"),
            (268_435_455, b"\xff\xff\xff\x7f"),
        ]
        for value, expected in cases:
            actual = bytes(encode_varlen(value))
            assert actual == expected, (
                f"encode_varlen({value}) = {actual!r}, expected {expected!r}"
            )

    def test_negative_raises(self) -> None:
        with raises(ValueError):
            encode_varlen(-1)

    def test_above_max_raises(self) -> None:
        with raises(ValueError):
            encode_varlen(268_435_456)

    def test_round_trips_through_decode(self) -> None:
        for value in (0, 5, 127, 128, 1_000, 268_435_455):
            encoded = encode_varlen(value)
            decoded, consumed = decode_varlen(memoryview(encoded), 0)
            assert decoded == value
            assert consumed == len(encoded)


class TestDecodeVarlen:
    def test_returns_zero_zero_on_incomplete(self) -> None:
        # Continuation bit set but no follow-up byte.
        decoded, consumed = decode_varlen(memoryview(b"\x80"), 0)
        assert decoded == 0
        assert consumed == 0

    def test_handles_offset_within_buffer(self) -> None:
        decoded, consumed = decode_varlen(memoryview(b"\xff\x7f\x05"), 0)
        assert decoded == 16_383
        assert consumed == 2

    def test_varlen_past_4_bytes_raises_protocol_error(self) -> None:
        # All 4 bytes set the continuation bit — malformed, not
        # "incomplete".  Must raise, not return (0, 0) and stall.
        with raises(MQTTProtocolError):
            decode_varlen(memoryview(b"\x80\x80\x80\x80"), 0)

    def test_returns_zero_zero_when_offset_past_end(self) -> None:
        decoded, consumed = decode_varlen(memoryview(b"\x05"), 1)
        assert decoded == 0
        assert consumed == 0


class TestEncodeString:
    def test_str_input_is_utf8_encoded(self) -> None:
        encoded = encode_string("hello")
        assert encoded == b"\x00\x05hello"

    def test_bytes_input_passthrough(self) -> None:
        encoded = encode_string(b"hello")
        assert encoded == b"\x00\x05hello"

    def test_empty_string_carries_zero_length(self) -> None:
        assert encode_string("") == b"\x00\x00"

    def test_unicode_length_is_byte_length_not_char_count(self) -> None:
        # Three-byte UTF-8 char ("£") + ASCII "x".
        encoded = encode_string("£x")
        assert encoded[:2] == b"\x00\x03"  # 3 bytes total


class TestTopicMatches:
    def test_matches(self) -> None:
        cases = [
            ("a/b/c", "a/b/c"),
            ("a/b/c", "a/+/c"),
            ("a/b/c", "+/+/+"),
            ("a/b/c", "a/b/#"),
            ("a/b/c", "a/#"),
            ("a/b/c", "#"),
            ("a/b", "a/+"),
            ("sensors/temperature/back-porch", "sensors/+/back-porch"),
            ("sensors/temperature/back-porch", "sensors/temperature/#"),
        ]
        for topic, pattern in cases:
            assert topic_matches(topic, pattern), (
                f"expected match: topic={topic!r} pattern={pattern!r}"
            )

    def test_does_not_match(self) -> None:
        cases = [
            ("a/b", "a/b/c"),
            ("a/b/c", "a/b"),  # extra topic level after pattern ends
            ("a/b/c/d", "a/+/c"),  # +'s only one level
            ("a/b/c", "x/+/+"),
            ("a", "+/+"),  # topic too short for pattern
        ]
        for topic, pattern in cases:
            assert not topic_matches(topic, pattern), (
                f"expected no match: topic={topic!r} pattern={pattern!r}"
            )

    def test_hash_must_be_last(self) -> None:
        # The original client returns False here per spec (#'s only
        # legal as the LAST level).  Implementation: # in non-final
        # position is treated as exact-match against literal "#".
        assert not topic_matches("a/b", "#/b")
