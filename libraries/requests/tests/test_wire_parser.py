"""Wire-format tests for chumicro_requests — streaming response parser
state machine: status line, headers, unknown length, and error latching.
"""

from chumicro_requests import (
    HttpOversizedError,
    HttpProtocolError,
    ParseState,
    ResponseParser,
)
from chumicro_requests.testing import canned_response

# ---------------------------------------------------------------------------
# Response parser — streaming state machine
# ---------------------------------------------------------------------------


class TestResponseParserStatusAndHeaders:
    """Status line and header parsing edge cases."""

    def test_simple_response_with_content_length(self):
        parser = ResponseParser()
        parser.feed(canned_response(body=b"hello"))
        assert parser.state == ParseState.DONE
        assert parser.status_code == 200
        assert parser.reason == "OK"
        assert parser.http_version == "HTTP/1.1"
        assert parser.headers["content-type"] == "text/plain"
        assert parser.body == b"hello"

    def test_status_line_split_across_feeds(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 20")
        assert parser.state == ParseState.STATUS  # not enough to advance yet
        parser.feed(b"4 No Content\r\n\r\n")
        assert parser.state == ParseState.DONE  # 204 has no body
        assert parser.status_code == 204

    def test_headers_split_across_feeds(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-")
        parser.feed(b"Length: 3\r\n")
        assert parser.state == ParseState.HEADERS
        parser.feed(b"\r\nabc")
        assert parser.state == ParseState.DONE
        assert parser.body == b"abc"

    def test_body_split_across_feeds(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nfirst")
        assert parser.state == ParseState.BODY
        assert parser.body == b"first"
        parser.feed(b"second")
        assert parser.state == ParseState.DONE
        assert parser.body == b"firstsecon"  # only 10 bytes — extra dropped

    def test_extra_bytes_after_complete_body_are_ignored(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nabc")
        assert parser.state == ParseState.DONE
        # Extra bytes after the body — server bug; parser already DONE.
        parser.feed(b"trailing-junk")
        assert parser.body == b"abc"

    def test_status_204_skips_body(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 204 No Content\r\n\r\n")
        assert parser.state == ParseState.DONE
        assert parser.status_code == 204
        assert parser.body == b""

    def test_status_304_skips_body(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 304 Not Modified\r\n\r\n")
        assert parser.state == ParseState.DONE
        assert parser.body == b""

    def test_status_1xx_interim_is_discarded_and_parser_awaits_final(self):
        # A 1xx interim response (100 Continue, 103 Early Hints) is not
        # the final response: the parser discards it and returns to
        # parsing the next status line, then completes on the real 200.
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 100 Continue\r\n\r\n")
        assert parser.state == ParseState.STATUS
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi")
        assert parser.state == ParseState.DONE
        assert parser.status_code == 200
        assert parser.body == b"hi"

    def test_status_103_early_hints_then_final_response(self):
        parser = ResponseParser()
        parser.feed(
            b"HTTP/1.1 103 Early Hints\r\n"
            b"Link: </style.css>; rel=preload\r\n\r\n",
        )
        assert parser.state == ParseState.STATUS
        parser.feed(b"HTTP/1.1 204 No Content\r\n\r\n")
        assert parser.state == ParseState.DONE
        assert parser.status_code == 204

    def test_zero_content_length_completes(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        assert parser.state == ParseState.DONE
        assert parser.body == b""

    def test_header_section_over_cap_fails_not_ooms(self):
        # A peer dribbling header bytes with no CRLF must latch ERROR at
        # the header-byte cap rather than growing the staging buffer
        # forever.  feed() latches self.error; the client re-raises it.
        parser = ResponseParser(max_header_bytes=1024)
        for _ in range(20):
            parser.feed(b"X" * 100)  # no CRLF; accumulates past 1024
            if parser.state == ParseState.ERROR:
                break
        assert parser.state == ParseState.ERROR
        assert isinstance(parser.error, HttpProtocolError)

    def test_large_body_reassembles_across_small_chunks(self):
        # The pre-allocated body path must reassemble a large
        # Content-Length body fed in small recv-sized chunks intact.
        body = bytes((index % 251) for index in range(4096))
        parser = ResponseParser(max_body_bytes=8192)
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 4096\r\n\r\n")
        offset = 0
        while offset < len(body):
            parser.feed(body[offset:offset + 200])
            offset += 200
        assert parser.state == ParseState.DONE
        assert parser.body == body

    def test_no_reason_phrase(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200\r\nContent-Length: 0\r\n\r\n")
        assert parser.status_code == 200
        assert parser.reason == ""

    def test_repeated_header_joined(self):
        parser = ResponseParser()
        parser.feed(
            b"HTTP/1.1 200 OK\r\n"
            b"Set-Cookie: a=1\r\n"
            b"Set-Cookie: b=2\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n",
        )
        assert parser.headers["set-cookie"] == "a=1, b=2"


class TestResponseParserLengthUnknown:
    """No Content-Length: read until peer closes."""

    def test_eof_completes_body(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\n\r\nstreaming-body")
        assert parser.state == ParseState.BODY
        parser.feed_eof()
        assert parser.state == ParseState.DONE
        assert parser.body == b"streaming-body"

    def test_eof_safe_after_done(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        parser.feed_eof()
        assert parser.state == ParseState.DONE

    def test_eof_after_error_is_safe(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 NOT-A-CODE 200\r\n")
        assert parser.state == ParseState.ERROR
        parser.feed_eof()
        assert parser.state == ParseState.ERROR

    def test_oversized_unknown_length_raises(self):
        parser = ResponseParser(max_body_bytes=8)
        parser.feed(b"HTTP/1.1 200 OK\r\n\r\n")
        parser.feed(b"x" * 16)
        assert parser.state == ParseState.ERROR
        assert isinstance(parser.error, HttpOversizedError)


class TestResponseParserErrors:
    """Malformed inputs latch ERROR state."""

    def test_malformed_status_line_too_few_parts(self):
        parser = ResponseParser()
        parser.feed(b"BROKEN\r\n")
        assert parser.state == ParseState.ERROR
        assert isinstance(parser.error, HttpProtocolError)

    def test_status_line_missing_http_prefix(self):
        parser = ResponseParser()
        parser.feed(b"NOT-HTTP 200 OK\r\n")
        assert parser.state == ParseState.ERROR

    def test_status_code_not_integer(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 not-a-code OK\r\n")
        assert parser.state == ParseState.ERROR

    def test_header_line_missing_colon(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nNoColonHere\r\n\r\n")
        assert parser.state == ParseState.ERROR

    def test_header_line_empty_name(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\n: novalue\r\n\r\n")
        assert parser.state == ParseState.ERROR

    def test_non_integer_content_length(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: lots\r\n\r\n")
        assert parser.state == ParseState.ERROR

    def test_negative_content_length(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\n")
        assert parser.state == ParseState.ERROR

    def test_content_length_past_cap(self):
        parser = ResponseParser(max_body_bytes=10)
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
        assert parser.state == ParseState.ERROR
        assert isinstance(parser.error, HttpOversizedError)

    def test_eof_mid_body_protocol_error(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nshort")
        parser.feed_eof()
        assert parser.state == ParseState.ERROR
        assert "Content-Length" in str(parser.error)

    def test_eof_mid_headers_protocol_error(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-")
        parser.feed_eof()
        assert parser.state == ParseState.ERROR

    def test_feed_after_done_is_noop(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        assert parser.state == ParseState.DONE
        parser.feed(b"")  # no-op
        parser.feed(b"junk")  # ignored
        assert parser.state == ParseState.DONE
