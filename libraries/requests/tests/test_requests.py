"""Tests for chumicro_requests slice 3a — plain HTTP GET against FakeSocket.

Decision 0040 §1: HttpClient is runner-shaped (check / handle), single
in-flight, single socket per request.  These tests cover URL parse,
header dict semantics, request encoding, the streaming response parser,
the runner contract, timeouts, busy-state enforcement, oversize policy
branches, and the chumicro_sockets_factory helper.

The fake transport is :class:`chumicro_sockets.testing.FakeSocket` —
the same one chumicro_mqtt's tests use, so the contract is exercised
across two libraries.
"""

import pytest
from chumicro_requests import (
    CaseInsensitiveDict,
    HttpBusyError,
    HttpClient,
    HttpError,
    HttpOversizedError,
    HttpProtocolError,
    HttpTimeoutError,
    HttpURLError,
    ParseState,
    Response,
    ResponseParser,
    WhenOversized,
    chumicro_sockets_factory,
    encode_request,
    parse_charset,
    parse_url,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_factory(socket_or_factory):
    """Return a connection_factory that hands out *socket_or_factory*.

    *socket_or_factory* can be either a single :class:`FakeSocket`
    (returned every call) or a zero-arg callable that builds a fresh
    one on demand.
    """
    def factory(host, port, use_tls):  # noqa: ARG001 — fake ignores args
        if callable(socket_or_factory):
            return socket_or_factory()
        return socket_or_factory

    return factory


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


def drive_until_done(client, handle, ticks, *, max_ticks=200, advance_ms=1):
    """Run handle/check until done; safety-cap at *max_ticks* iterations."""
    for _ in range(max_ticks):
        if handle.done:
            return
        if client.check(ticks.ticks_ms()):
            client.handle(ticks.ticks_ms())
        ticks.advance(advance_ms)
    raise AssertionError(f"handle never completed within {max_ticks} ticks")


def make_client(*, socket_or_factory=None, **kwargs):
    """Construct an HttpClient wired to FakeTicks + a FakeSocket factory."""
    ticks = FakeTicks()
    socket = socket_or_factory if socket_or_factory is not None else FakeSocket()
    client = HttpClient(
        connection_factory=make_factory(socket),
        ticks_ms_func=ticks.ticks_ms,
        ticks_add_func=ticks.ticks_add,
        ticks_diff_func=ticks.ticks_diff,
        **kwargs,
    )
    return client, ticks, socket


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
        with pytest.raises(HttpURLError, match="http://"):
            parse_url("ftp://example.com/")

    def test_missing_host(self):
        with pytest.raises(HttpURLError, match="missing host"):
            parse_url("http:///path")

    def test_empty_after_scheme(self):
        with pytest.raises(HttpURLError, match="missing host"):
            parse_url("http://")

    def test_missing_host_with_port(self):
        with pytest.raises(HttpURLError, match="missing host"):
            parse_url("http://:8080/")

    def test_non_integer_port(self):
        with pytest.raises(HttpURLError, match="non-integer port"):
            parse_url("http://example.com:abc/")

    def test_port_out_of_range(self):
        with pytest.raises(HttpURLError, match="out of range"):
            parse_url("http://example.com:99999/")

    def test_port_zero_rejected(self):
        with pytest.raises(HttpURLError, match="out of range"):
            parse_url("http://example.com:0/")

    def test_url_must_be_string(self):
        with pytest.raises(HttpURLError, match="must be str"):
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
# Response body decode (slice 3b)
# ---------------------------------------------------------------------------


class TestResponseDecode:
    """``.encoding`` / ``.text`` / ``.json()`` cover decode + JSON parse."""

    def _make(self, *, body, content_type=None, encoding=None):
        headers = CaseInsensitiveDict()
        if content_type is not None:
            headers["Content-Type"] = content_type
        return Response(
            status_code=200,
            reason="OK",
            http_version="HTTP/1.1",
            headers=headers,
            body=body,
            url="http://example.test/",
            encoding=encoding,
        )

    def test_text_default_utf8(self):
        response = self._make(body="café".encode())
        assert response.encoding == "utf-8"
        assert response.text == "café"

    def test_text_uses_content_type_charset(self):
        response = self._make(
            body="café".encode("latin-1"),
            content_type="text/plain; charset=latin-1",
        )
        assert response.encoding == "latin-1"
        assert response.text == "café"

    def test_encoding_override_via_constructor(self):
        response = self._make(
            body="café".encode("latin-1"),
            content_type="text/plain; charset=utf-8",  # server lies
            encoding="latin-1",
        )
        assert response.encoding == "latin-1"
        assert response.text == "café"

    def test_encoding_setter_overrides(self):
        response = self._make(body="café".encode("latin-1"))
        response.encoding = "latin-1"
        assert response.encoding == "latin-1"
        assert response.text == "café"

    def test_json_decode(self):
        response = self._make(
            body=b'{"temp_f": 72, "ok": true}',
            content_type="application/json",
        )
        result = response.json()
        assert result == {"temp_f": 72, "ok": True}

    def test_json_invalid_raises(self):
        response = self._make(body=b"not-json", content_type="application/json")
        with pytest.raises(ValueError):
            response.json()

    def test_text_decode_error_propagates(self):
        # Latin-1-only byte that's invalid UTF-8.
        response = self._make(body=b"\xff", content_type="text/plain; charset=utf-8")
        with pytest.raises(UnicodeDecodeError):
            _ = response.text


# ---------------------------------------------------------------------------
# HttpClient — runner contract + GET path
# ---------------------------------------------------------------------------


class TestHttpClientGet:
    """End-to-end GET against FakeSocket — slice 3a happy path + structure."""

    def test_simple_get_returns_response(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"hello"))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.get("http://example.test/")
        assert not handle.done
        drive_until_done(client, handle, ticks)

        response = handle.result
        assert isinstance(response, Response)
        assert response.status_code == 200
        assert response.reason == "OK"
        assert response.http_version == "HTTP/1.1"
        assert response.body == b"hello"
        assert response.headers["content-type"] == "text/plain"
        assert response.url == "http://example.test/"

    def test_request_bytes_sent_to_socket(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.get("http://example.test/api/widgets")
        drive_until_done(client, handle, ticks)

        assert socket.sent.startswith(b"GET /api/widgets HTTP/1.1\r\n")
        assert b"Host: example.test\r\n" in socket.sent
        assert socket.sent.endswith(b"\r\n\r\n")

    def test_non_default_port_in_host_header(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.get("http://example.test:8080/")
        drive_until_done(client, handle, ticks)

        assert b"Host: example.test:8080\r\n" in socket.sent

    def test_caller_headers_passed_through(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.get(
            "http://example.test/",
            headers={"Authorization": "Bearer secret"},
        )
        drive_until_done(client, handle, ticks)

        assert b"Authorization: Bearer secret\r\n" in socket.sent

    def test_user_agent_override_at_construction(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(
            socket_or_factory=socket, user_agent="custom-agent/9",
        )

        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        assert b"User-Agent: custom-agent/9\r\n" in socket.sent

    def test_https_url_dispatches_with_use_tls_true(self):
        """Slice 3c: ``https://`` URLs route to the connection_factory
        with ``use_tls=True`` and skip the port in the Host header
        when it equals 443 (the scheme default)."""
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"secured"))
        captured = []

        def factory(host, port, use_tls):
            captured.append((host, port, use_tls))
            return socket

        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=factory,
            ticks_ms_func=ticks.ticks_ms,
            ticks_add_func=ticks.ticks_add,
            ticks_diff_func=ticks.ticks_diff,
        )
        handle = client.get("https://example.test/secret")
        drive_until_done(client, handle, ticks)
        assert handle.result.body == b"secured"
        assert captured == [("example.test", 443, True)]
        # Host header omits the default 443 port.
        assert b"Host: example.test\r\n" in socket.sent

    def test_https_explicit_port_kept_in_host_header(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        captured = []

        def factory(host, port, use_tls):
            captured.append((host, port, use_tls))
            return socket

        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=factory,
            ticks_ms_func=ticks.ticks_ms,
            ticks_add_func=ticks.ticks_add,
            ticks_diff_func=ticks.ticks_diff,
        )
        handle = client.get("https://example.test:8443/")
        drive_until_done(client, handle, ticks)
        assert captured == [("example.test", 8443, True)]
        assert b"Host: example.test:8443\r\n" in socket.sent

    def test_socket_closed_after_completion(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"x"))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert socket.closed is True
        assert client.busy is False


class TestHttpClientRunnerContract:
    """``check`` and ``handle`` satisfy Decision 0014."""

    def test_check_false_when_idle(self):
        client, ticks, _ = make_client()
        assert client.check(ticks.ticks_ms()) is False

    def test_check_true_while_in_flight(self):
        socket = FakeSocket()
        # Don't queue a response — leave the request stalled in receive.
        client, ticks, _ = make_client(socket_or_factory=socket)
        client.get("http://example.test/")
        assert client.check(ticks.ticks_ms()) is True

    def test_handle_when_idle_is_noop(self):
        client, ticks, _ = make_client()
        client.handle(ticks.ticks_ms())  # safe; nothing to do
        assert client.busy is False

    def test_busy_property_tracks_in_flight(self):
        socket = FakeSocket()
        client, ticks, _ = make_client(socket_or_factory=socket)
        assert client.busy is False
        client.get("http://example.test/")
        assert client.busy is True


class TestHttpClientBusyError:
    """A second request while one is in flight raises HttpBusyError."""

    def test_second_get_during_recv_raises(self):
        socket = FakeSocket()  # no response queued — request will hang
        client, _ticks, _ = make_client(socket_or_factory=socket)
        client.get("http://example.test/one")
        with pytest.raises(HttpBusyError, match="busy"):
            client.get("http://example.test/two")

    def test_can_issue_after_completion(self):
        # Two FakeSockets, returned in sequence.
        sockets = [FakeSocket(), FakeSocket()]
        sockets[0].enqueue_recv(canned_response(body=b"first"))
        sockets[1].enqueue_recv(canned_response(body=b"second"))
        index = {"position": 0}

        def factory_callable():
            socket = sockets[index["position"]]
            index["position"] += 1
            return socket

        client, ticks, _ = make_client(socket_or_factory=factory_callable)

        first = client.get("http://example.test/one")
        drive_until_done(client, first, ticks)
        assert first.result.body == b"first"

        second = client.get("http://example.test/two")
        drive_until_done(client, second, ticks)
        assert second.result.body == b"second"


class _StalledRecvSocket(FakeSocket):
    """FakeSocket that always raises EAGAIN on recv_into.

    Models a real non-blocking socket that the peer hasn't written
    to — the production-shaped condition that fires per-request
    ``timeout_ms`` budgets.  FakeSocket's default behavior of
    returning 0 on an empty queue is a clean-peer-close signal in
    real socket semantics, which the production client correctly
    treats as end-of-response.  This subclass is the right fixture
    for "stalled connection" tests.
    """

    def recv_into(self, buffer, nbytes=0):
        if self._closed:
            raise OSError(9, "socket closed")
        raise OSError(11, "would block")


class TestHttpClientTimeout:
    """Per-request ``timeout_ms`` fails the request when expired."""

    def test_timeout_fires_when_no_response(self):
        socket = _StalledRecvSocket()
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/", timeout_ms=50)
        for _ in range(60):
            if handle.done:
                break
            client.handle(ticks.ticks_ms())
            ticks.advance(2)
        assert handle.done is True
        assert isinstance(handle.error, HttpTimeoutError)
        with pytest.raises(HttpTimeoutError):
            _ = handle.result

    def test_default_timeout_used_when_none(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"ok"))
        client, ticks, _ = make_client(
            socket_or_factory=socket, default_timeout_ms=100,
        )
        handle = client.get("http://example.test/")  # no per-call timeout_ms
        drive_until_done(client, handle, ticks)
        assert handle.result.body == b"ok"


class TestHttpClientErrors:
    """Socket / protocol errors propagate to the handle."""

    def test_protocol_error_fails_handle(self):
        socket = FakeSocket()
        socket.enqueue_recv(b"BROKEN-NOT-HTTP\r\n")
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert isinstance(handle.error, HttpProtocolError)

    def test_socket_error_fails_handle(self):
        class BrokenSocket(FakeSocket):
            def send(self, data):
                raise OSError(99, "boom")

        socket = BrokenSocket()
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert isinstance(handle.error, HttpError)
        assert "socket error" in str(handle.error)

    def test_send_eagain_retries_next_tick(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"hi"))
        socket.enqueue_eagain_for_send(2)  # first two send calls return EAGAIN
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert handle.result.body == b"hi"

    def test_recv_eagain_during_response_retries(self):
        socket = FakeSocket()
        socket.enqueue_eagain_for_recv(2)
        socket.enqueue_recv(canned_response(body=b"yo"))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert handle.result.body == b"yo"

    def test_peer_close_completes_unknown_length_body(self):
        socket = FakeSocket()
        # No Content-Length → length-unknown body.  FakeSocket returns
        # 0 once the recv queue drains, which mirrors a clean peer
        # close — the production client calls feed_eof() and the
        # parser transitions BODY -> DONE.
        socket.enqueue_recv(b"HTTP/1.1 200 OK\r\n\r\nstreamed-bytes")
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        assert handle.result.body == b"streamed-bytes"

    def test_result_before_done_raises(self):
        socket = FakeSocket()
        client, _ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        with pytest.raises(HttpError, match="before done"):
            _ = handle.result


# ---------------------------------------------------------------------------
# HttpClient POST / PUT / PATCH / DELETE — slice 3d
# ---------------------------------------------------------------------------


class TestHttpClientPost:
    """POST + body + json= helper."""

    def test_post_with_bytes_body(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"ok"))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.post("http://example.test/api", body=b"payload-bytes")
        drive_until_done(client, handle, ticks)
        assert handle.result.body == b"ok"
        assert socket.sent.startswith(b"POST /api HTTP/1.1\r\n")
        assert b"Content-Length: 13\r\n" in socket.sent
        assert socket.sent.endswith(b"\r\n\r\npayload-bytes")

    def test_post_with_str_body_encodes_utf8(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.post("http://example.test/api", body="café")
        drive_until_done(client, handle, ticks)
        # "café".encode("utf-8") == b"caf\xc3\xa9" (5 bytes)
        assert b"Content-Length: 5\r\n" in socket.sent
        assert socket.sent.endswith(b"\r\n\r\ncaf\xc3\xa9")

    def test_post_with_json_serializes_and_sets_content_type(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b'{"received":true}'))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.post(
            "http://example.test/api",
            json={"sensor_id": 42, "temp_f": 72},
        )
        drive_until_done(client, handle, ticks)
        assert handle.result.status_code == 200
        # Body is JSON-encoded
        assert b'"sensor_id": 42' in socket.sent or b'"sensor_id":42' in socket.sent
        assert b"Content-Type: application/json\r\n" in socket.sent
        assert b"Content-Length:" in socket.sent

    def test_post_caller_content_type_overrides_json_default(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.post(
            "http://example.test/api",
            json={"k": "v"},
            headers={"Content-Type": "application/json+custom"},
        )
        drive_until_done(client, handle, ticks)
        assert b"Content-Type: application/json+custom\r\n" in socket.sent
        # The default application/json should NOT also be present
        assert b"Content-Type: application/json\r\n" not in socket.sent

    def test_post_body_and_json_mutually_exclusive(self):
        client, _ticks, _ = make_client()
        with pytest.raises(ValueError, match="not both"):
            client.post("http://example.test/", body=b"x", json={"k": "v"})

    def test_post_rejects_non_bytes_non_str_body(self):
        client, _ticks, _ = make_client()
        with pytest.raises(TypeError, match="bytes / bytearray / str"):
            client.post("http://example.test/", body=42)

    def test_post_with_bytearray_body(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.post("http://example.test/", body=bytearray(b"ba"))
        drive_until_done(client, handle, ticks)
        assert socket.sent.endswith(b"\r\n\r\nba")

    def test_post_no_body(self):
        """POST with neither body= nor json= — empty body, no Content-Length."""
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.post("http://example.test/")
        drive_until_done(client, handle, ticks)
        # No body → no Content-Length added by encode_request
        assert b"Content-Length:" not in socket.sent
        assert socket.sent.startswith(b"POST / HTTP/1.1\r\n")

    def test_put_request(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.put("http://example.test/widgets/42", body=b"updated")
        drive_until_done(client, handle, ticks)
        assert socket.sent.startswith(b"PUT /widgets/42 HTTP/1.1\r\n")
        assert socket.sent.endswith(b"\r\n\r\nupdated")

    def test_patch_request_with_json(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.patch(
            "http://example.test/widgets/42",
            json={"name": "renamed"},
        )
        drive_until_done(client, handle, ticks)
        assert socket.sent.startswith(b"PATCH /widgets/42 HTTP/1.1\r\n")
        assert b"Content-Type: application/json\r\n" in socket.sent

    def test_delete_request(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b""))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.delete("http://example.test/widgets/42")
        drive_until_done(client, handle, ticks)
        assert socket.sent.startswith(b"DELETE /widgets/42 HTTP/1.1\r\n")
        # DELETE never has a body in v1.
        assert socket.sent.endswith(b"\r\n\r\n")
        assert b"Content-Length:" not in socket.sent

    def test_post_busy_error_when_in_flight(self):
        socket = FakeSocket()
        client, _ticks, _ = make_client(socket_or_factory=socket)
        client.post("http://example.test/one", body=b"first")
        with pytest.raises(HttpBusyError):
            client.post("http://example.test/two", body=b"second")

    def test_post_url_error_propagates(self):
        client, _ticks, _ = make_client()
        with pytest.raises(HttpURLError):
            client.post("ftp://bad/", body=b"x")


class TestMergeDefaultHeader:
    """Helper: caller-supplied headers override the default."""

    def test_dict_input_overrides_default(self):
        from chumicro_requests.client import _merge_default_header

        merged = _merge_default_header(
            {"Content-Type": "text/plain"},
            "Content-Type", "application/json",
        )
        assert merged["Content-Type"] == "text/plain"

    def test_iterable_input(self):
        from chumicro_requests.client import _merge_default_header

        merged = _merge_default_header(
            [("X-Custom", "v")],
            "Content-Type", "application/json",
        )
        assert merged["x-custom"] == "v"
        assert merged["Content-Type"] == "application/json"

    def test_caseinsensitive_dict_input(self):
        from chumicro_requests._wire import CaseInsensitiveDict
        from chumicro_requests.client import _merge_default_header

        original = CaseInsensitiveDict()
        original["X-Custom"] = "v"
        merged = _merge_default_header(
            original, "Content-Type", "application/json",
        )
        assert merged["X-Custom"] == "v"

    def test_none_input_keeps_default(self):
        from chumicro_requests.client import _merge_default_header

        merged = _merge_default_header(None, "Content-Type", "application/json")
        assert merged["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# HttpClient — recv budget per tick
# ---------------------------------------------------------------------------


class _CountingSocket(FakeSocket):
    """FakeSocket that records bytes consumed per recv_into call."""

    def __init__(self):
        super().__init__()
        self.bytes_received_total = 0

    def recv_into(self, buffer, nbytes=0):
        result = super().recv_into(buffer, nbytes)
        if result > 0:
            self.bytes_received_total += result
        return result


class TestHttpClientRecvBudget:
    """``recv_budget_per_tick`` keeps each tick LED-friendly."""

    def test_budget_caps_bytes_per_tick(self):
        body = b"x" * 4096
        socket = _CountingSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            recv_budget_per_tick=512,
            max_body_bytes=8192,
        )
        handle = client.get("http://example.test/")
        # Drive sending only — first tick handles SENDING + transitions to RECEIVING.
        client.handle(ticks.ticks_ms())  # SEND
        socket.bytes_received_total = 0
        client.handle(ticks.ticks_ms())  # RECV (one tick)
        assert socket.bytes_received_total <= 512
        assert not handle.done

    def test_default_budget_is_1024(self):
        socket = _CountingSocket()
        socket.enqueue_recv(canned_response(body=b"x" * 8192))
        client, ticks, _ = make_client(
            socket_or_factory=socket, max_body_bytes=16384,
        )
        handle = client.get("http://example.test/")
        client.handle(ticks.ticks_ms())  # SEND
        socket.bytes_received_total = 0
        client.handle(ticks.ticks_ms())  # RECV (one tick)
        assert socket.bytes_received_total <= 1024
        assert not handle.done

    def test_budget_eventually_drains_full_payload(self):
        body = b"y" * 4096
        socket = _CountingSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            recv_budget_per_tick=1024,
            max_body_bytes=8192,
        )
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks, max_ticks=20)
        assert handle.result.body == body


# ---------------------------------------------------------------------------
# HttpClient — oversize policies
# ---------------------------------------------------------------------------


class TestHttpClientOversizePolicy:
    """``WhenOversized`` branches: silent drop, drop+event, fail."""

    def test_drop_silent_yields_empty_body(self):
        body = b"x" * 100
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            max_body_bytes=10,
            when_oversized=WhenOversized.DROP_SILENT,
        )
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        response = handle.result
        assert response.body == b""
        assert response.oversized_dropped is True
        assert response.status_code == 200

    def test_drop_with_event_fires_callback(self):
        body = b"x" * 100
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            max_body_bytes=10,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
        )
        events = []
        client.on_oversized = lambda url, error: events.append((url, error))

        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        assert handle.result.oversized_dropped is True
        assert len(events) == 1
        assert events[0][0] == "http://example.test/"
        assert isinstance(events[0][1], HttpOversizedError)

    def test_disconnect_policy_fails_request(self):
        body = b"x" * 100
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            max_body_bytes=10,
            when_oversized=WhenOversized.DISCONNECT,
        )
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        assert isinstance(handle.error, HttpOversizedError)


# ---------------------------------------------------------------------------
# chumicro_sockets_factory helper
# ---------------------------------------------------------------------------


class TestChumicroSocketsFactory:
    """The convenience factory dispatches on ``use_tls``."""

    def test_plain_tcp_routes_to_tcp_client_socket(self, monkeypatch):
        calls = []

        def fake_tcp(host, port, *, radio):
            calls.append(("tcp", host, port, radio))
            return "tcp-socket"

        def fake_tls(host, port, *, context, radio):
            calls.append(("tls", host, port, context, radio))
            return "tls-socket"  # pragma: no cover - shouldn't be hit here

        from chumicro_sockets import (
            tcp_client_socket as real_tcp,  # noqa: F401 — verify import path
        )

        monkeypatch.setattr("chumicro_sockets.tcp_client_socket", fake_tcp)
        monkeypatch.setattr("chumicro_sockets.tls_client_socket", fake_tls)

        factory = chumicro_sockets_factory(radio="my-radio")
        result = factory("example.test", 80, False)
        assert result == "tcp-socket"
        assert calls == [("tcp", "example.test", 80, "my-radio")]

    def test_tls_routes_to_tls_client_socket(self, monkeypatch):
        calls = []

        def fake_tcp(host, port, *, radio):
            calls.append(("tcp", host, port, radio))
            return "tcp-socket"  # pragma: no cover

        def fake_tls(host, port, *, context, radio):
            calls.append(("tls", host, port, context, radio))
            return "tls-socket"

        monkeypatch.setattr("chumicro_sockets.tcp_client_socket", fake_tcp)
        monkeypatch.setattr("chumicro_sockets.tls_client_socket", fake_tls)

        factory = chumicro_sockets_factory(radio=None, ssl_context="ctx")
        result = factory("example.test", 443, True)
        assert result == "tls-socket"
        assert calls == [("tls", "example.test", 443, "ctx", None)]


# ---------------------------------------------------------------------------
# FakeHttpClient — testing helper
# ---------------------------------------------------------------------------


class TestFakeHttpClient:
    """The host-only :class:`FakeHttpClient` mirrors the real client surface."""

    def test_scripted_response_completes_after_handle(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(
            status=200,
            body=b'{"temp_f": 72}',
            headers={"Content-Type": "application/json"},
        )
        handle = fake.get("http://api.example.test/weather")
        assert not handle.done
        assert fake.busy is True
        assert fake.check(now_ms=0) is True

        fake.handle(now_ms=0)
        assert handle.done
        assert fake.busy is False
        response = handle.result
        assert response.status_code == 200
        assert response.body == b'{"temp_f": 72}'
        assert response.headers["content-type"] == "application/json"
        assert response.url == "http://api.example.test/weather"

    def test_call_recording(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.get("http://example.test/", headers={"X-Foo": "bar"}, timeout_ms=99)

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call.method == "GET"
        assert call.url == "http://example.test/"
        assert call.headers == {"X-Foo": "bar"}
        assert call.timeout_ms == 99

    def test_scripted_error_propagates(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_error(HttpTimeoutError("simulated timeout"))
        handle = fake.get("http://example.test/")
        fake.handle(now_ms=0)
        assert handle.done
        assert isinstance(handle.error, HttpTimeoutError)
        with pytest.raises(HttpTimeoutError, match="simulated"):
            _ = handle.result

    def test_enqueue_error_rejects_non_http_error(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        with pytest.raises(TypeError, match="HttpError"):
            fake.enqueue_error(ValueError("not an HttpError"))

    def test_get_without_scripted_response_raises(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        with pytest.raises(HttpError, match="no scripted responses"):
            fake.get("http://example.test/")

    def test_busy_during_in_flight(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.get("http://example.test/")
        with pytest.raises(HttpBusyError, match="busy"):
            fake.get("http://example.test/two")

    def test_check_false_when_idle(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        assert fake.check(now_ms=0) is False

    def test_handle_when_idle_is_noop(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.handle(now_ms=0)  # safe no-op

    def test_responses_consumed_fifo(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(status=200, body=b"first")
        fake.enqueue_response(status=404, body=b"")

        handle_one = fake.get("http://example.test/one")
        fake.handle(now_ms=0)
        assert handle_one.result.body == b"first"

        handle_two = fake.get("http://example.test/two")
        fake.handle(now_ms=0)
        assert handle_two.result.status_code == 404

    def test_headers_as_iterable(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(headers=[("X-Custom", "v"), ("Server", "nginx")])
        handle = fake.get("http://example.test/")
        fake.handle(now_ms=0)
        assert handle.result.headers["x-custom"] == "v"
        assert handle.result.headers["server"] == "nginx"

    def test_oversized_dropped_flag_round_trip(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(status=200, body=b"", oversized_dropped=True)
        handle = fake.get("http://example.test/")
        fake.handle(now_ms=0)
        assert handle.result.oversized_dropped is True
