"""http_server wire tests: request-parser body buffer tiers,
build_response, encode_response."""

from chumicro_http_server import (
    RequestParser,
    RequestParseState,
    build_response,
    encode_response,
)
from chumicro_test_harness.assertions import raises


class TestRequestParserBodyBufferTiers:
    """Tier 1 (caller-supplied steady buffer, no alloc), Tier 2 (sized
    rebind for bigger-but-allowed bodies), Tier 3 (413 before alloc).
    Mirrors :class:`chumicro_requests._wire.HttpResponseParser`'s three
    tiers but with HTTP-shaped error semantics at tier 3 — Content-Length
    is always known up-front (no chunked decode), so the sized rebind
    happens at headers-complete time, not lazily per chunk.
    """

    def test_body_fits_in_supplied_buffer_writes_in_place(self):
        body_buffer = bytearray(1024)
        body_buffer_view = memoryview(body_buffer)
        parser = RequestParser(
            body_buffer=body_buffer,
            body_buffer_view=body_buffer_view,
        )
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 5\r\n\r\n"
            b"hello",
        )
        assert parser.state == RequestParseState.DONE
        assert parser.body == b"hello"
        # The body buffer object the caller supplied is the same object
        # the parser wrote into — no sized rebind happened.
        assert parser._body is body_buffer  # noqa: SLF001
        assert body_buffer[:5] == b"hello"

    def test_body_at_capacity_writes_in_place(self):
        # Exactly at capacity — still tier 1, no rebind.
        body_buffer = bytearray(5)
        parser = RequestParser(
            body_buffer=body_buffer,
            max_body_bytes=10,
        )
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 5\r\n\r\n"
            b"hello",
        )
        assert parser.state == RequestParseState.DONE
        assert parser.body == b"hello"
        assert parser._body is body_buffer  # noqa: SLF001

    def test_body_overflow_rebinds_sized_to_fit(self):
        body_buffer = bytearray(8)
        parser = RequestParser(
            body_buffer=body_buffer,
            max_body_bytes=1024,
        )
        payload = b"A" * 100  # > 8 but < 1024
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 100\r\n\r\n"
            + payload,
        )
        assert parser.state == RequestParseState.DONE
        assert parser.body == payload
        # Sized rebind happened: ``_body`` is now a fresh bytearray of
        # exactly the body length, and the caller's buffer was NOT
        # mutated (still all zeros, ready for the next request).
        assert parser._body is not body_buffer  # noqa: SLF001
        assert len(parser._body) == 100  # noqa: SLF001
        assert body_buffer == bytearray(8)

    def test_standalone_parser_starts_empty(self):
        # No body_buffer supplied — capacity 0.  First body triggers a
        # sized rebind to the exact Content-Length.  Confirms the
        # constraint: never pre-alloc a default-sized buffer in
        # standalone use (the on-device fragmentation tests measured
        # 1024-byte defaults as a regression).
        parser = RequestParser()
        assert parser._body_capacity == 0  # noqa: SLF001
        assert len(parser._body) == 0  # noqa: SLF001
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 5\r\n\r\n"
            b"hello",
        )
        assert parser.state == RequestParseState.DONE
        assert parser.body == b"hello"
        assert parser._body_capacity == 5  # noqa: SLF001


class TestBuildResponse:
    def test_default_200(self):
        response = build_response()
        assert response.status_code == 200
        assert response.reason == "OK"
        assert response.body == b""

    def test_text_default_content_type(self):
        response = build_response(200, text="hello")
        assert response.body == b"hello"
        assert response.headers["Content-Type"] == "text/plain; charset=utf-8"

    def test_html_default_content_type(self):
        response = build_response(200, html="<h1>Hi</h1>")
        assert response.body == b"<h1>Hi</h1>"
        assert response.headers["Content-Type"] == "text/html; charset=utf-8"

    def test_json_default_content_type(self):
        response = build_response(200, json={"k": "v"})
        assert response.body == b'{"k": "v"}'
        assert response.headers["Content-Type"] == "application/json"

    def test_bytes_body_no_default_content_type(self):
        response = build_response(200, body=b"\x00\x01\x02")
        assert response.body == b"\x00\x01\x02"
        assert "Content-Type" not in response.headers

    def test_str_body_encoded_utf8_no_default_content_type(self):
        response = build_response(200, body="hello")
        assert response.body == b"hello"

    def test_caller_headers_override_default(self):
        response = build_response(
            200, json={"k": "v"},
            headers={"Content-Type": "application/vnd.custom+json"},
        )
        assert response.headers["Content-Type"] == "application/vnd.custom+json"

    def test_multiple_body_kwargs_rejected(self):
        with raises(ValueError, match="at most one"):
            build_response(200, body=b"x", json={"k": "v"})

    def test_non_bytes_str_body_rejected(self):
        with raises(TypeError, match="bytes / bytearray / str"):
            build_response(200, body=42)

    def test_unknown_status_uses_unknown_reason(self):
        response = build_response(599)
        assert response.reason == "Unknown"

    def test_iterable_headers_input(self):
        response = build_response(
            200, text="ok",
            headers=[("X-Custom", "v")],
        )
        assert response.headers["X-Custom"] == "v"


class TestEncodeResponse:
    def test_encodes_status_headers_body(self):
        response = build_response(200, text="hello")
        wire = encode_response(response)
        assert wire.startswith(b"HTTP/1.1 200 OK\r\n")
        assert b"Content-Length: 5\r\n" in wire
        assert b"Content-Type: text/plain; charset=utf-8\r\n" in wire
        assert b"Connection: close\r\n" in wire
        assert wire.endswith(b"\r\n\r\nhello")

    def test_empty_body_zero_content_length(self):
        response = build_response(204)
        wire = encode_response(response)
        assert b"Content-Length: 0\r\n" in wire
        assert wire.endswith(b"\r\n\r\n")
