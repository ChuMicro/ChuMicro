"""Tests for the UTF-8 streaming decoder."""

from __future__ import annotations

import pytest
from chumicro_repl.framing import Utf8StreamDecoder


class TestSingleChunkDecoding:
    """A whole code-point arriving in one chunk decodes immediately."""

    def test_ascii_passes_through(self):
        decoder = Utf8StreamDecoder()
        assert decoder.decode(b"hello\n") == "hello\n"

    def test_two_byte_codepoint_complete(self):
        decoder = Utf8StreamDecoder()
        # "ñ" — U+00F1 — bytes c3 b1
        assert decoder.decode(b"\xc3\xb1") == "ñ"

    def test_three_byte_codepoint_complete(self):
        decoder = Utf8StreamDecoder()
        # "中" — U+4E2D — bytes e4 b8 ad
        assert decoder.decode(b"\xe4\xb8\xad") == "中"

    def test_four_byte_codepoint_complete(self):
        decoder = Utf8StreamDecoder()
        # 🙂 — U+1F642 — bytes f0 9f 99 82
        assert decoder.decode(b"\xf0\x9f\x99\x82") == "\U0001f642"

    def test_empty_chunk_returns_empty_string(self):
        decoder = Utf8StreamDecoder()
        assert decoder.decode(b"") == ""


class TestSplitAcrossChunks:
    """Code-points split across chunk boundaries decode lazily."""

    def test_two_byte_split(self):
        decoder = Utf8StreamDecoder()
        assert decoder.decode(b"\xc3") == ""
        assert decoder.decode(b"\xb1") == "ñ"

    def test_three_byte_split_after_first(self):
        decoder = Utf8StreamDecoder()
        assert decoder.decode(b"\xe4") == ""
        assert decoder.decode(b"\xb8\xad") == "中"

    def test_three_byte_split_after_second(self):
        decoder = Utf8StreamDecoder()
        assert decoder.decode(b"\xe4\xb8") == ""
        assert decoder.decode(b"\xad") == "中"

    def test_four_byte_split_into_singletons(self):
        decoder = Utf8StreamDecoder()
        chunks = [b"\xf0", b"\x9f", b"\x99", b"\x82"]
        outputs = [decoder.decode(chunk) for chunk in chunks]
        # Only the final chunk yields the code point.
        assert outputs == ["", "", "", "\U0001f642"]

    def test_partial_then_more_ascii(self):
        decoder = Utf8StreamDecoder()
        # "a" + start of ñ + rest of ñ + "b"
        assert decoder.decode(b"a\xc3") == "a"
        assert decoder.decode(b"\xb1b") == "ñb"


class TestErrorReplacement:
    """Invalid bytes never raise — they become U+FFFD."""

    def test_lone_continuation_byte_replaces(self):
        decoder = Utf8StreamDecoder()
        # 0xb1 is a continuation byte with no leading byte.
        decoded = decoder.decode(b"\xb1after")
        assert "after" in decoded
        assert "�" in decoded

    def test_truncated_at_eof_flushes_replacement(self):
        decoder = Utf8StreamDecoder()
        # Send an incomplete 4-byte sequence, then flush.
        assert decoder.decode(b"\xf0\x9f") == ""
        flushed = decoder.flush()
        assert flushed == "�"

    def test_flush_on_empty_buffer_is_empty(self):
        decoder = Utf8StreamDecoder()
        assert decoder.flush() == ""


class TestMixedAsciiAndMultibyte:
    """Realistic REPL output mixes ASCII with occasional emoji or accents."""

    def test_emoji_in_traceback_line(self):
        decoder = Utf8StreamDecoder()
        message = "Traceback in 🙂 module\n".encode()
        assert decoder.decode(message) == "Traceback in 🙂 module\n"

    def test_emoji_split_across_multiple_chunks(self):
        decoder = Utf8StreamDecoder()
        full = "ok 🙂 done\n".encode()
        decoded = []
        for offset in range(len(full)):
            decoded.append(decoder.decode(full[offset:offset + 1]))
        assert "".join(decoded) == "ok 🙂 done\n"

class TestMalformedLeadByte:
    """A leading byte that does not match any UTF-8 length pattern is flushed."""

    def test_invalid_leading_byte_produces_replacement(self):
        decoder = Utf8StreamDecoder()
        # 0xfe / 0xff are not valid UTF-8 leading bytes anywhere.
        decoded = decoder.decode(b"good\xfeafter")
        assert decoded.startswith("good")
        assert "�" in decoded
        assert decoded.endswith("after")


@pytest.mark.parametrize(
    "chunks,expected",
    [
        ([b"hi"], "hi"),
        ([b"\xc3", b"\xb1"], "ñ"),
        ([b"a\xf0", b"\x9f\x99", b"\x82b"], "a\U0001f642b"),
    ],
)
def test_streaming_chunks_concatenate_correctly(chunks, expected):
    decoder = Utf8StreamDecoder()
    parts = [decoder.decode(chunk) for chunk in chunks]
    parts.append(decoder.flush())
    assert "".join(parts) == expected
