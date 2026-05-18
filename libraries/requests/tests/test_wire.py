"""Wire-format tests for chumicro_requests — URL / header / encode /
streaming response parser / redirect resolution.

Mirrors ``chumicro_requests._wire``: ``parse_url``, ``parse_charset``,
``CaseInsensitiveDict``, ``encode_request``, ``ResponseParser`` (status,
headers, length-unknown, errors, chunked), ``resolve_redirect_url``.
``HttpClient``-level behaviour lives in the sibling ``test_client.py``;
pytest-fixture variants in ``test_requests_pytest.py``.
"""

from chumicro_requests import (
    CaseInsensitiveDict,
    HttpOversizedError,
    HttpProtocolError,
    HttpURLError,
    ParseState,
    ResponseParser,
    encode_request,
    parse_charset,
    parse_url,
    resolve_redirect_url,
)
from chumicro_test_harness.assertions import raises


def canned_response(*, status=200, reason="OK", body=b"", extra_headers=()):
    """Build an HTTP/1.1 response byte-string with Content-Length."""
    lines = [f"HTTP/1.1 {status} {reason}\r\n".encode("ascii")]
    lines.append(f"Content-Length: {len(body)}\r\n".encode("ascii"))
    lines.append(b"Content-Type: text/plain\r\n")
    for name, value in extra_headers:
        lines.append(f"{name}: {value}\r\n".encode("ascii"))
    lines.append(b"\r\n")
    lines.append(body)
    return b"".join(lines)


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------


class TestParseURL:
    """``parse_url`` covers HTTP/HTTPS schemes + default ports."""

    def test_plain_http_default_port(self):
        assert parse_url("http://example.com/") == ("http", "example.com", 80, "/")

    def test_plain_http_no_path(self):
        assert parse_url("http://example.com") == ("http", "example.com", 80, "/")

    def test_explicit_port_and_path(self):
        result = parse_url("http://example.com:8080/path?query=1")
        assert result == ("http", "example.com", 8080, "/path?query=1")

    def test_https_default_port(self):
        assert parse_url("https://example.com/") == ("https", "example.com", 443, "/")

    def test_https_explicit_port(self):
        result = parse_url("https://example.com:8443/api")
        assert result == ("https", "example.com", 8443, "/api")

    def test_unsupported_scheme(self):
        with raises(HttpURLError, match="http://"):
            parse_url("ftp://example.com/")

    def test_missing_host(self):
        with raises(HttpURLError, match="missing host"):
            parse_url("http:///path")

    def test_empty_after_scheme(self):
        with raises(HttpURLError, match="missing host"):
            parse_url("http://")

    def test_missing_host_with_port(self):
        with raises(HttpURLError, match="missing host"):
            parse_url("http://:8080/")

    def test_non_integer_port(self):
        with raises(HttpURLError, match="non-integer port"):
            parse_url("http://example.com:abc/")

    def test_port_out_of_range(self):
        with raises(HttpURLError, match="out of range"):
            parse_url("http://example.com:99999/")

    def test_port_zero_rejected(self):
        with raises(HttpURLError, match="out of range"):
            parse_url("http://example.com:0/")

    def test_url_must_be_string(self):
        with raises(HttpURLError, match="must be str"):
            parse_url(b"http://example.com/")


# ---------------------------------------------------------------------------
# Content-Type charset parsing
# ---------------------------------------------------------------------------


class TestParseCharset:
    """``parse_charset`` extracts ``charset=`` from Content-Type values."""

    def test_no_header_defaults_utf8(self):
        assert parse_charset(None) == "utf-8"

    def test_empty_header_defaults_utf8(self):
        assert parse_charset("") == "utf-8"

    def test_charset_explicit(self):
        assert parse_charset("text/html; charset=utf-8") == "utf-8"

    def test_charset_quoted(self):
        assert parse_charset('text/html; charset="ISO-8859-1"') == "ISO-8859-1"

    def test_charset_uppercase_token(self):
        assert parse_charset("text/html; CHARSET=latin-1") == "latin-1"

    def test_no_charset_param_defaults_utf8(self):
        assert parse_charset("application/json") == "utf-8"

    def test_charset_after_other_params(self):
        result = parse_charset("text/html; boundary=x; charset=cp1252")
        assert result == "cp1252"

    def test_blank_charset_value_defaults_utf8(self):
        assert parse_charset("text/plain; charset=") == "utf-8"


# ---------------------------------------------------------------------------
# Case-insensitive header dict
# ---------------------------------------------------------------------------


class TestCaseInsensitiveDict:
    """Header lookups fold case; original casing preserved on iteration."""

    def test_set_and_get(self):
        headers = CaseInsensitiveDict()
        headers["Content-Type"] = "text/plain"
        assert headers["content-type"] == "text/plain"
        assert headers["CONTENT-TYPE"] == "text/plain"

    def test_contains(self):
        headers = CaseInsensitiveDict()
        headers["X-Foo"] = "bar"
        assert "x-foo" in headers
        assert "X-FOO" in headers
        assert "missing" not in headers

    def test_iter_preserves_original_case(self):
        headers = CaseInsensitiveDict()
        headers["Content-Type"] = "text/plain"
        headers["X-Custom-Header"] = "v"
        assert list(headers) == ["Content-Type", "X-Custom-Header"]

    def test_len(self):
        headers = CaseInsensitiveDict()
        assert len(headers) == 0
        headers["a"] = "1"
        headers["B"] = "2"
        assert len(headers) == 2

    def test_get_default(self):
        headers = CaseInsensitiveDict()
        assert headers.get("missing") is None
        assert headers.get("missing", "fallback") == "fallback"

    def test_items(self):
        headers = CaseInsensitiveDict()
        headers["A"] = "1"
        headers["B"] = "2"
        assert list(headers.items()) == [("A", "1"), ("B", "2")]

    def test_add_appends_with_join(self):
        """RFC 7230 §3.2.2: repeated header lines join with ``, ``."""
        headers = CaseInsensitiveDict()
        headers.add("Set-Cookie", "session=abc")
        headers.add("Set-Cookie", "tracker=xyz")
        assert headers["set-cookie"] == "session=abc, tracker=xyz"

    def test_add_then_setitem_overrides(self):
        headers = CaseInsensitiveDict()
        headers.add("X-Foo", "first")
        headers["x-foo"] = "second"
        assert headers["X-Foo"] == "second"

    def test_add_new_key_behaves_like_setitem(self):
        headers = CaseInsensitiveDict()
        headers.add("X-Solo", "value")
        assert headers["x-solo"] == "value"

    def test_equality_same_keys_and_values(self):
        first = CaseInsensitiveDict()
        first["A"] = "1"
        second = CaseInsensitiveDict()
        second["a"] = "1"
        assert first == second

    def test_equality_different_lengths(self):
        first = CaseInsensitiveDict()
        first["A"] = "1"
        second = CaseInsensitiveDict()
        second["A"] = "1"
        second["B"] = "2"
        assert first != second

    def test_equality_different_values(self):
        first = CaseInsensitiveDict()
        first["A"] = "1"
        second = CaseInsensitiveDict()
        second["A"] = "2"
        assert first != second

    def test_equality_different_keys(self):
        first = CaseInsensitiveDict()
        first["A"] = "1"
        second = CaseInsensitiveDict()
        second["B"] = "1"
        assert first != second

    def test_equality_against_non_dict(self):
        headers = CaseInsensitiveDict()
        # NotImplemented -> Python falls back; against a plain dict
        # Python returns False after both sides return NotImplemented.
        assert headers != {"a": 1}

    def test_repr_round_trip_keys(self):
        headers = CaseInsensitiveDict()
        headers["A"] = "1"
        headers["B"] = "2"
        assert "A" in repr(headers) and "B" in repr(headers)


# ---------------------------------------------------------------------------
# Request encoding
# ---------------------------------------------------------------------------


class TestEncodeRequest:
    """``encode_request`` produces RFC-shaped HTTP/1.1 request bytes."""

    def test_get_minimal_defaults(self):
        request_bytes = encode_request("GET", "example.com", "/")
        assert request_bytes.startswith(b"GET / HTTP/1.1\r\n")
        assert b"Host: example.com\r\n" in request_bytes
        assert b"User-Agent: chumicro-requests/0.1\r\n" in request_bytes
        assert b"Accept: */*\r\n" in request_bytes
        assert b"Accept-Encoding: identity\r\n" in request_bytes
        assert b"Connection: close\r\n" in request_bytes
        assert request_bytes.endswith(b"\r\n\r\n")

    def test_user_agent_override(self):
        request_bytes = encode_request("GET", "h", "/", user_agent="my-ua/1.0")
        assert b"User-Agent: my-ua/1.0\r\n" in request_bytes

    def test_caller_headers_override_defaults(self):
        request_bytes = encode_request(
            "GET", "example.com", "/", headers={"Accept": "application/json"},
        )
        assert b"Accept: application/json\r\n" in request_bytes
        assert b"Accept: */*\r\n" not in request_bytes

    def test_caller_headers_as_iterable(self):
        request_bytes = encode_request(
            "GET", "h", "/", headers=[("X-Custom", "v"), ("Authorization", "Bearer x")],
        )
        assert b"X-Custom: v\r\n" in request_bytes
        assert b"Authorization: Bearer x\r\n" in request_bytes

    def test_caller_headers_as_caseinsensitive_dict(self):
        custom = CaseInsensitiveDict()
        custom["X-Foo"] = "bar"
        request_bytes = encode_request("GET", "h", "/", headers=custom)
        assert b"X-Foo: bar\r\n" in request_bytes

    def test_body_adds_content_length(self):
        request_bytes = encode_request("POST", "h", "/", body=b"hello")
        assert b"Content-Length: 5\r\n" in request_bytes
        assert request_bytes.endswith(b"\r\nhello")

    def test_crlf_in_path_rejected(self):
        with raises(HttpURLError, match="control character"):
            encode_request("GET", "h", "/x\r\nX-Evil: 1", headers=None)

    def test_newline_in_method_rejected(self):
        with raises(HttpURLError, match="control character"):
            encode_request("GE\nT", "h", "/")

    def test_crlf_in_header_value_rejected(self):
        with raises(HttpURLError, match="control character"):
            encode_request("GET", "h", "/", headers={"X-A": "v\r\nX-Evil: 1"})

    def test_nul_in_header_name_rejected(self):
        with raises(HttpURLError, match="control character"):
            encode_request("GET", "h", "/", headers={"X-\x00": "v"})


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

    def test_status_1xx_skips_body(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 100 Continue\r\n\r\n")
        assert parser.state == ParseState.DONE

    def test_zero_content_length_completes(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        assert parser.state == ParseState.DONE
        assert parser.body == b""

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

    def test_eof_idempotent_after_done(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        parser.feed_eof()  # safe even after DONE
        assert parser.state == ParseState.DONE

    def test_eof_after_error_is_safe(self):
        parser = ResponseParser()
        parser.feed(b"HTTP/1.1 NOT-A-CODE 200\r\n")
        assert parser.state == ParseState.ERROR
        parser.feed_eof()  # idempotent
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


# ---------------------------------------------------------------------------
# ResponseParser chunked transfer-encoding — slice 3f
# ---------------------------------------------------------------------------


class TestResponseParserChunked:
    """RFC 7230 §4.1 chunked decode."""

    def _chunked_response(self, *chunks, status=200, extra_headers=()):
        """Build a chunked-encoded response from raw bytes chunks.

        Each *chunk* is the raw payload of one chunk; the helper
        builds the size lines + CRLFs + terminating zero-chunk.
        """
        parts = [
            f"HTTP/1.1 {status} OK\r\n".encode("ascii"),
            b"Transfer-Encoding: chunked\r\n",
            b"Content-Type: text/plain\r\n",
        ]
        for name, value in extra_headers:
            parts.append(f"{name}: {value}\r\n".encode("ascii"))
        parts.append(b"\r\n")
        for chunk in chunks:
            parts.append(f"{len(chunk):x}\r\n".encode("ascii"))
            parts.append(chunk)
            parts.append(b"\r\n")
        parts.append(b"0\r\n\r\n")  # last-chunk + empty trailer
        return b"".join(parts)

    def test_single_chunk(self):
        parser = ResponseParser()
        parser.feed(self._chunked_response(b"hello world"))
        assert parser.state == ParseState.DONE
        assert parser.body == b"hello world"

    def test_multi_chunk_concatenates(self):
        parser = ResponseParser()
        parser.feed(self._chunked_response(b"Wiki", b"pedia ", b"in chunks."))
        assert parser.state == ParseState.DONE
        assert parser.body == b"Wikipedia in chunks."

    def test_empty_chunked_body(self):
        parser = ResponseParser()
        parser.feed(self._chunked_response())  # just `0\r\n\r\n`
        assert parser.state == ParseState.DONE
        assert parser.body == b""

    def test_chunked_split_across_feeds(self):
        full = self._chunked_response(b"hello", b"world")
        # Drip-feed one byte at a time — exercises the "buffer too short" return
        # paths in every state.
        parser = ResponseParser()
        for byte_index in range(len(full)):
            parser.feed(full[byte_index:byte_index + 1])
        assert parser.state == ParseState.DONE
        assert parser.body == b"helloworld"

    def test_chunk_extension_ignored(self):
        """A `;name=value` extension on the chunk-size line is silently dropped."""
        parser = ResponseParser()
        # Chunk size 5 with extension `;myext=foo`, then data, then 0
        body_bytes = (
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5;myext=foo\r\n"
            b"hello\r\n"
            b"0\r\n\r\n"
        )
        parser.feed(body_bytes)
        assert parser.state == ParseState.DONE
        assert parser.body == b"hello"

    def test_trailer_headers_discarded(self):
        """Trailer headers between last-chunk and empty CRLF are accepted + ignored."""
        parser = ResponseParser()
        body_bytes = (
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\nhello\r\n"
            b"0\r\n"
            b"X-Trailer: extra-info\r\n"
            b"X-Other: more-info\r\n"
            b"\r\n"
        )
        parser.feed(body_bytes)
        assert parser.state == ParseState.DONE
        assert parser.body == b"hello"

    def test_transfer_encoding_takes_precedence_over_content_length(self):
        """Per RFC 7230 §3.3.3, when both are present, chunked wins."""
        parser = ResponseParser()
        body_bytes = (
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"Content-Length: 999\r\n"  # ignored
            b"\r\n"
            b"5\r\nhello\r\n"
            b"0\r\n\r\n"
        )
        parser.feed(body_bytes)
        assert parser.state == ParseState.DONE
        assert parser.body == b"hello"

    def test_unsupported_transfer_encoding_fails(self):
        parser = ResponseParser()
        body_bytes = (
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: gzip\r\n"
            b"\r\n"
        )
        parser.feed(body_bytes)
        assert parser.state == ParseState.ERROR
        assert "gzip" in str(parser.error)

    def test_non_hex_chunk_size_fails(self):
        parser = ResponseParser()
        parser.feed(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"NOT-HEX\r\n",
        )
        assert parser.state == ParseState.ERROR
        assert "non-hex" in str(parser.error)

    def test_empty_chunk_size_line_fails(self):
        parser = ResponseParser()
        parser.feed(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"\r\n",
        )
        assert parser.state == ParseState.ERROR

    def test_missing_crlf_after_chunk_data_fails(self):
        parser = ResponseParser()
        # Chunk size 5, then 5 bytes, then "XX" instead of CRLF
        parser.feed(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\nhelloXX0\r\n\r\n",
        )
        assert parser.state == ParseState.ERROR
        assert "CRLF after chunk" in str(parser.error)

    def test_chunked_oversized_fails(self):
        parser = ResponseParser(max_body_bytes=10)
        parser.feed(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"100\r\n",  # 256 bytes > cap of 10
        )
        assert parser.state == ParseState.ERROR
        assert isinstance(parser.error, HttpOversizedError)

    def test_chunked_eof_mid_data_fails(self):
        parser = ResponseParser()
        parser.feed(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"100\r\nshort",  # claims 256 bytes, only 5 sent
        )
        assert parser.state == ParseState.CHUNK_DATA
        parser.feed_eof()
        assert parser.state == ParseState.ERROR
        assert "mid-chunked-body" in str(parser.error)

    def test_transfer_encoding_with_whitespace(self):
        """`chunked` may have surrounding whitespace per RFC 7230 §3.2."""
        parser = ResponseParser()
        body_bytes = (
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding:   chunked  \r\n"  # leading/trailing space
            b"\r\n"
            b"5\r\nhello\r\n0\r\n\r\n"
        )
        parser.feed(body_bytes)
        assert parser.state == ParseState.DONE
        assert parser.body == b"hello"


# ---------------------------------------------------------------------------
# Redirect URL resolution
# ---------------------------------------------------------------------------


class TestResolveRedirectURL:
    """``resolve_redirect_url`` covers all three RFC 7231 §7.1.2 shapes."""

    def test_absolute_url_returned_verbatim(self):
        result = resolve_redirect_url(
            "http://example.com/start",
            "https://other.com/dest",
        )
        assert result == "https://other.com/dest"

    def test_absolute_path_keeps_scheme_host_port(self):
        result = resolve_redirect_url(
            "https://example.com:8443/api/v1",
            "/api/v2",
        )
        assert result == "https://example.com:8443/api/v2"

    def test_absolute_path_default_port_omitted(self):
        result = resolve_redirect_url(
            "http://example.com/start",
            "/dest",
        )
        assert result == "http://example.com/dest"

    def test_relative_path_replaces_last_segment(self):
        result = resolve_redirect_url(
            "http://example.com/api/v1/widgets",
            "trinkets",
        )
        assert result == "http://example.com/api/v1/trinkets"

    def test_relative_path_at_root(self):
        result = resolve_redirect_url(
            "http://example.com/",
            "dest",
        )
        assert result == "http://example.com/dest"

    def test_relative_path_strips_query(self):
        """Query string on the original URL is dropped before joining."""
        result = resolve_redirect_url(
            "http://example.com/api/list?page=2",
            "items",
        )
        assert result == "http://example.com/api/items"

    def test_empty_location_raises(self):
        with raises(HttpURLError, match="empty"):
            resolve_redirect_url("http://example.com/", "")
