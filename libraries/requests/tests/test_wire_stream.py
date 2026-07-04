"""Wire-format tests for chumicro_requests — streamed-body staging in
``ResponseParser(stream_body=True)``: fixed window, read cursor,
backpressure accounting, and the cap bypasses.
"""

from chumicro_requests import (
    HttpError,
    ParseState,
    ResponseParser,
)


def _content_length_head(body_size, *, status=200):
    """Status line + headers for a Content-Length response, no body bytes."""
    return (
        f"HTTP/1.1 {status} OK\r\n"
        f"Content-Length: {body_size}\r\n"
        "Content-Type: application/octet-stream\r\n"
        "\r\n"
    ).encode("ascii")


def _drain(parser, *, chunk_size=8):
    """Read every staged byte out through ``read_body_into``."""
    scratch = bytearray(chunk_size)
    collected = bytearray()
    while True:
        count = parser.read_body_into(scratch)
        if count == 0:
            return bytes(collected)
        collected.extend(scratch[:count])


class TestStreamStagingWindow:
    """The staging window: fixed capacity, cursor reset, free accounting."""

    def test_body_streams_through_a_window_smaller_than_the_body(self):
        """A 40-byte Content-Length body passes through a 16-byte window:
        feeds bounded by body_free() alternate with reads, and the
        reassembled bytes match the original body."""
        parser = ResponseParser(stream_body=True, body_buffer=bytearray(16))
        body = bytes(range(40))
        parser.feed(_content_length_head(40))
        assert parser.headers_complete is True
        collected = bytearray()
        scratch = bytearray(8)
        offset = 0
        while parser.state != ParseState.DONE or parser.body_free() < 16:
            free = parser.body_free()
            if offset < len(body) and free > 0:
                take = min(free, len(body) - offset)
                parser.feed(body[offset:offset + take])
                offset += take
            count = parser.read_body_into(scratch)
            if count:
                collected.extend(scratch[:count])
            elif parser.state == ParseState.DONE:
                break
        collected.extend(_drain(parser))
        assert parser.state == ParseState.DONE
        assert bytes(collected) == body

    def test_body_free_reflects_staged_bytes_and_full_drain_resets(self):
        parser = ResponseParser(stream_body=True, body_buffer=bytearray(16))
        parser.feed(_content_length_head(20))
        assert parser.body_free() == 16
        parser.feed(b"x" * 10)
        assert parser.body_free() == 6
        # Partial read advances the read cursor but frees nothing (the
        # window is linear; space returns on the full drain).
        scratch = bytearray(4)
        assert parser.read_body_into(scratch) == 4
        assert parser.body_free() == 6
        # Full drain resets both cursors: the whole window is writable.
        assert parser.read_body_into(bytearray(16)) == 6
        assert parser.body_free() == 16

    def test_read_body_into_returns_zero_when_nothing_staged(self):
        parser = ResponseParser(stream_body=True, body_buffer=bytearray(16))
        parser.feed(_content_length_head(5))
        assert parser.read_body_into(bytearray(4)) == 0

    def test_overflowing_the_window_latches_http_error(self):
        """Feeding more body than body_free() is a feeder-contract break:
        the parser latches ERROR with an HttpError naming the staging
        overflow instead of growing the window."""
        parser = ResponseParser(stream_body=True, body_buffer=bytearray(8))
        parser.feed(_content_length_head(64))
        parser.feed(b"y" * 16)  # 16 > 8-byte window
        assert parser.state == ParseState.ERROR
        assert isinstance(parser.error, HttpError)
        assert "staging overflow" in str(parser.error)

    def test_discard_body_empties_the_window(self):
        parser = ResponseParser(stream_body=True, body_buffer=bytearray(16))
        parser.feed(_content_length_head(20))
        parser.feed(b"z" * 12)
        parser.discard_body()
        assert parser.body_free() == 16
        assert parser.read_body_into(bytearray(16)) == 0


class TestStreamCapBypasses:
    """``max_body_bytes`` does not gate streamed bodies — the window does."""

    def test_content_length_over_cap_streams(self):
        parser = ResponseParser(
            stream_body=True, body_buffer=bytearray(32), max_body_bytes=10,
        )
        parser.feed(_content_length_head(64))
        assert parser.state == ParseState.BODY
        for _ in range(4):
            parser.feed(b"a" * 16)
            assert _drain(parser) == b"a" * 16
        assert parser.state == ParseState.DONE

    def test_chunked_over_cap_streams(self):
        parser = ResponseParser(
            stream_body=True, body_buffer=bytearray(32), max_body_bytes=10,
        )
        parser.feed(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n",
        )
        collected = bytearray()
        for _ in range(3):
            parser.feed(b"10\r\n" + b"b" * 16 + b"\r\n")  # 3 x 16 > cap of 10
            collected.extend(_drain(parser))
        parser.feed(b"0\r\n\r\n")
        assert parser.state == ParseState.DONE
        assert bytes(collected) == b"b" * 48

    def test_length_unknown_over_cap_streams_until_eof(self):
        parser = ResponseParser(
            stream_body=True, body_buffer=bytearray(32), max_body_bytes=10,
        )
        parser.feed(b"HTTP/1.1 200 OK\r\n\r\n")
        collected = bytearray()
        for _ in range(3):
            parser.feed(b"c" * 16)
            collected.extend(_drain(parser))
        parser.feed_eof()
        assert parser.state == ParseState.DONE
        assert bytes(collected) == b"c" * 48


class TestStreamHeadersComplete:
    """``headers_complete`` marks the final (non-1xx) header block only."""

    def test_false_before_headers_and_across_interim_1xx(self):
        parser = ResponseParser(stream_body=True, body_buffer=bytearray(16))
        parser.feed(b"HTTP/1.1 100 Continue\r\n")
        assert parser.headers_complete is False
        parser.feed(b"\r\n")  # 1xx block ends; parser resets to STATUS
        assert parser.headers_complete is False
        parser.feed(_content_length_head(3))
        assert parser.headers_complete is True
        parser.feed(b"abc")
        assert parser.state == ParseState.DONE
        assert _drain(parser) == b"abc"

    def test_default_stream_window_allocates_when_no_buffer_given(self):
        """stream_body=True with no body_buffer self-allocates the default
        window, so a standalone parser streams without extra setup."""
        parser = ResponseParser(stream_body=True)
        parser.feed(_content_length_head(5))
        parser.feed(b"hello")
        assert parser.state == ParseState.DONE
        assert _drain(parser) == b"hello"
