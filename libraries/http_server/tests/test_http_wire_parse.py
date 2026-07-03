"""http_server wire tests: split-target sentinel, query parsing,
request parser. Sibling slices: other test_http_*.py."""

from chumicro_http_server import (
    RequestParser,
    RequestParseState,
    ServerHeadersTooLargeError,
    ServerOversizedError,
    ServerProtocolError,
    ServerRequestLineTooLargeError,
    parse_query,
    split_target,
)
from chumicro_http_server.testing import request_bytes


class TestSplitTarget:
    def test_path_only(self):
        assert split_target("/") == ("/", "")

    def test_path_with_query(self):
        assert split_target("/api?k=v") == ("/api", "k=v")

    def test_path_with_query_and_multiple_params(self):
        assert split_target("/x?a=1&b=2") == ("/x", "a=1&b=2")

    def test_question_mark_only(self):
        assert split_target("/?") == ("/", "")


class TestParseQuery:
    def test_empty(self):
        assert len(parse_query("")) == 0

    def test_single_pair(self):
        result = parse_query("k=v")
        assert result["k"] == "v"

    def test_multiple_pairs(self):
        result = parse_query("a=1&b=2")
        assert result["a"] == "1"
        assert result["b"] == "2"

    def test_value_less_param(self):
        result = parse_query("flag")
        assert result["flag"] == ""

    def test_empty_pair_skipped(self):
        result = parse_query("a=1&&b=2")
        assert result["a"] == "1"
        assert result["b"] == "2"

    def test_repeated_keys_join(self):
        result = parse_query("k=1&k=2")
        assert result["k"] == "1, 2"

    def test_keys_case_folded_and_merged(self):
        # parse_query stores into a CaseInsensitiveDict, so keys differing
        # only in case fold together into one lowercase entry and their
        # values join with ", " — the documented limitation, since URL
        # query keys are case-sensitive.
        result = parse_query("Foo=1&foo=2")
        assert len(result) == 1
        assert result["foo"] == "1, 2"


class TestRequestParser:
    def test_simple_get(self):
        parser = RequestParser()
        parser.feed(request_bytes(method="GET", path="/api"))
        assert parser.state == RequestParseState.DONE
        assert parser.method == "GET"
        assert parser.target == "/api"
        assert parser.http_version == "HTTP/1.1"

    def test_request_with_body(self):
        parser = RequestParser()
        parser.feed(request_bytes(method="POST", path="/", body=b"hello"))
        assert parser.state == RequestParseState.DONE
        assert parser.body == b"hello"

    def test_request_split_across_feeds(self):
        parser = RequestParser()
        full = request_bytes(method="POST", path="/", body=b"world")
        for byte_index in range(len(full)):
            parser.feed(full[byte_index:byte_index + 1])
        assert parser.state == RequestParseState.DONE
        assert parser.body == b"world"

    def test_headers_preserved_case_insensitive(self):
        parser = RequestParser()
        parser.feed(request_bytes(
            headers=[("Host", "example.test"), ("X-Custom", "value")],
        ))
        assert parser.headers["host"] == "example.test"
        assert parser.headers["X-CUSTOM"] == "value"

    def test_malformed_request_line_two_parts(self):
        parser = RequestParser()
        parser.feed(b"GET /\r\n")
        assert parser.state == RequestParseState.ERROR
        assert isinstance(parser.error, ServerProtocolError)

    def test_request_line_missing_http_prefix(self):
        parser = RequestParser()
        parser.feed(b"GET / NOT-HTTP/1.1\r\n")
        assert parser.state == RequestParseState.ERROR

    def test_empty_method(self):
        parser = RequestParser()
        parser.feed(b" / HTTP/1.1\r\n")
        assert parser.state == RequestParseState.ERROR

    def test_empty_target(self):
        parser = RequestParser()
        parser.feed(b"GET  HTTP/1.1\r\n")
        assert parser.state == RequestParseState.ERROR

    def test_negative_content_length(self):
        parser = RequestParser()
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: -5\r\n\r\n",
        )
        assert parser.state == RequestParseState.ERROR

    def test_non_integer_content_length(self):
        parser = RequestParser()
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: lots\r\n\r\n",
        )
        assert parser.state == RequestParseState.ERROR

    def test_transfer_encoding_rejected(self):
        # Chunked request bodies are unsupported; framing as zero-length
        # would let a smuggled body ride into the next request, so the
        # parser rejects with 400.
        parser = RequestParser()
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n"
            b"5\r\nhello\r\n0\r\n\r\n",
        )
        assert parser.state == RequestParseState.ERROR
        assert isinstance(parser.error, ServerProtocolError)

    def test_oversized_content_length_raises_oversized(self):
        parser = RequestParser(max_body_bytes=10)
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 9999\r\n\r\n",
        )
        assert parser.state == RequestParseState.ERROR
        assert isinstance(parser.error, ServerOversizedError)
        assert parser.error.reported_length == 9999

    def test_zero_content_length_completes(self):
        parser = RequestParser()
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 0\r\n\r\n",
        )
        assert parser.state == RequestParseState.DONE
        assert parser.body == b""

    def test_no_content_length_means_no_body(self):
        parser = RequestParser()
        parser.feed(b"GET / HTTP/1.1\r\n\r\n")
        assert parser.state == RequestParseState.DONE

    def test_header_missing_colon(self):
        parser = RequestParser()
        parser.feed(
            b"GET / HTTP/1.1\r\n"
            b"NoColon\r\n\r\n",
        )
        assert parser.state == RequestParseState.ERROR

    def test_eof_mid_headers_protocol_error(self):
        parser = RequestParser()
        parser.feed(b"GET / HTTP/1.1\r\nHost: x")
        parser.feed_eof()
        assert parser.state == RequestParseState.ERROR

    def test_eof_mid_body_protocol_error(self):
        parser = RequestParser()
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 100\r\n\r\n"
            b"short",
        )
        parser.feed_eof()
        assert parser.state == RequestParseState.ERROR


class TestRequestLineCap:
    """Request line capped at max_request_line_bytes: a no-CRLF dribble
    is refused at the cap instead of growing, an exact-cap line passes,
    and an over-cap line raises 414-mapped ServerRequestLineTooLargeError.
    """

    def test_no_crlf_dribble_refused_at_cap(self):
        # A byte-at-a-time dribble with no CRLF stops growing the buffer
        # once it passes the cap, raising 414 rather than buffering until
        # the request-timeout deadline.
        parser = RequestParser(max_request_line_bytes=16)
        for _ in range(64):
            parser.feed(b"A")
            if parser.state == RequestParseState.ERROR:
                break
        assert parser.state == RequestParseState.ERROR
        assert isinstance(parser.error, ServerRequestLineTooLargeError)
        # Buffer never grew far past the cap — at most one byte over.
        assert parser._live_len() <= 17

    def test_one_big_chunk_no_crlf_refused(self):
        # A single oversized chunk with no CRLF is caught by the same
        # length check, independent of chunk size.
        parser = RequestParser(max_request_line_bytes=16)
        parser.feed(b"B" * 4096)
        assert parser.state == RequestParseState.ERROR
        assert isinstance(parser.error, ServerRequestLineTooLargeError)

    def test_exact_cap_line_passes(self):
        # "GET /123456 HTTP/1.1" is exactly 20 bytes; with the cap set to
        # 20 the line plus its CRLF parses cleanly.
        line = b"GET /123456 HTTP/1.1"
        assert len(line) == 20
        parser = RequestParser(max_request_line_bytes=20)
        parser.feed(line + b"\r\n\r\n")
        assert parser.state == RequestParseState.DONE
        assert parser.target == "/123456"

    def test_exact_cap_line_split_before_crlf_waits(self):
        # The exact-cap line with no CRLF yet stays in REQUEST_LINE (a
        # length of exactly the cap is allowed); the CRLF in a later
        # feed completes it.
        line = b"GET /123456 HTTP/1.1"
        parser = RequestParser(max_request_line_bytes=20)
        parser.feed(line)
        assert parser.state == RequestParseState.REQUEST_LINE
        parser.feed(b"\r\n\r\n")
        assert parser.state == RequestParseState.DONE

    def test_one_over_cap_line_raises_414(self):
        # A line one byte longer than the cap (still no CRLF) trips 414.
        parser = RequestParser(max_request_line_bytes=20)
        parser.feed(b"GET /1234567 HTTP/1.1")  # 21 bytes, no CRLF
        assert parser.state == RequestParseState.ERROR
        assert isinstance(parser.error, ServerRequestLineTooLargeError)

    def test_over_cap_line_with_crlf_in_same_feed_raises_414(self):
        # The full line plus its CRLF arrive in one feed and exceed the
        # cap.  Before the pre-slice check this parsed (the cap was soft
        # by up to one recv chunk); now crlf_index > cap trips 414.
        parser = RequestParser(max_request_line_bytes=20)
        parser.feed(b"GET /1234567 HTTP/1.1\r\n\r\n")  # 21-byte line + CRLF
        assert parser.state == RequestParseState.ERROR
        assert isinstance(parser.error, ServerRequestLineTooLargeError)
        assert parser.error.status_code == 414

    def test_default_request_line_well_within_cap(self):
        # A normal request line is far below the 1 KB default and parses
        # without tripping the cap.
        parser = RequestParser()
        parser.feed(b"GET /api/widgets?page=2 HTTP/1.1\r\n\r\n")
        assert parser.state == RequestParseState.DONE


class TestHeadersCap:
    """Header section capped at max_headers_bytes: an oversized header
    section raises 431-mapped ServerHeadersTooLargeError, whether one big
    header line or many small ones, and a section at the cap passes.
    """

    def test_oversized_single_header_raises_431(self):
        parser = RequestParser(max_headers_bytes=32)
        parser.feed(b"GET / HTTP/1.1\r\n")
        parser.feed(b"X-Big: " + b"v" * 200 + b"\r\n\r\n")
        assert parser.state == RequestParseState.ERROR
        assert isinstance(parser.error, ServerHeadersTooLargeError)
        assert parser.error.status_code == 431

    def test_many_small_headers_sum_past_cap(self):
        # Each header line is small and consumed individually, but their
        # running total crosses the cap — the section-total counter,
        # not just the unconsumed buffer, catches it.
        parser = RequestParser(max_headers_bytes=64)
        parser.feed(b"GET / HTTP/1.1\r\n")
        for index in range(40):
            parser.feed(f"H{index}: v\r\n".encode("ascii"))
            if parser.state == RequestParseState.ERROR:
                break
        assert parser.state == RequestParseState.ERROR
        assert isinstance(parser.error, ServerHeadersTooLargeError)

    def test_no_crlf_header_dribble_refused_at_cap(self):
        # A header line that dribbles in with no CRLF stops growing the
        # buffer once the section total passes the cap.
        parser = RequestParser(max_headers_bytes=32)
        parser.feed(b"GET / HTTP/1.1\r\n")
        for _ in range(128):
            parser.feed(b"Z")
            if parser.state == RequestParseState.ERROR:
                break
        assert parser.state == RequestParseState.ERROR
        assert isinstance(parser.error, ServerHeadersTooLargeError)
        assert parser._live_len() <= 33

    def test_header_section_at_cap_passes(self):
        # A header section whose total bytes (line + CRLF + the empty
        # terminating CRLF) land exactly on the cap parses cleanly.
        # "Host: x\r\n" is 9 bytes, "\r\n" terminator is 2 → 11 total.
        parser = RequestParser(max_headers_bytes=11)
        parser.feed(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        assert parser.state == RequestParseState.DONE
        assert parser.headers["Host"] == "x"

    def test_default_headers_well_within_cap(self):
        parser = RequestParser()
        parser.feed(
            b"GET / HTTP/1.1\r\n"
            b"Host: device.local\r\n"
            b"Accept: */*\r\n\r\n",
        )
        assert parser.state == RequestParseState.DONE
