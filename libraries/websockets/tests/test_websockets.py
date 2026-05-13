"""Tests for chumicro_websockets — slice 1 (wire format).

Covers the public wire-level surface from
:mod:`chumicro_websockets._wire`:

* Exception hierarchy.
* :class:`CaseInsensitiveDict`.
* :func:`parse_ws_url`.
* :func:`make_websocket_key` + :func:`derive_accept_key` (RFC 6455
  §4.2.2 worked example included).
* Client / server opening-handshake encoders.
* Streaming :class:`HandshakeResponseParser` /
  :class:`HandshakeRequestParser`.
* :class:`FrameParser` framing math (header, length encodings,
  mask, control / data, fragmentation, oversize, reserved-bit
  rejection, control-frame interleave).
* :func:`encode_frame` (masked + unmasked).
* :func:`encode_close_payload` / :func:`parse_close_payload`.
* :func:`validate_text_payload`.
"""

import struct

from chumicro_test_harness.assertions import raises
from chumicro_websockets import (
    CLOSE_BAD_DATA,
    CLOSE_GOING_AWAY,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_CONTINUATION,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    WebSocketError,
    WebSocketHandshakeError,
    WebSocketProtocolError,
    WebSocketState,
    WebSocketURLError,
    derive_accept_key,
    make_websocket_key,
    parse_ws_url,
)
from chumicro_websockets._wire import (
    CLOSE_ABNORMAL,
    DEFAULT_MAX_MESSAGE_BYTES,
    MAX_CONTROL_PAYLOAD_BYTES,
    WS_MAGIC_GUID,
    WS_VERSION,
    CaseInsensitiveDict,
    FrameParser,
    FrameParseState,
    HandshakeParseState,
    HandshakeRequestParser,
    HandshakeResponseParser,
    encode_client_handshake,
    encode_close_payload,
    encode_frame,
    encode_server_handshake_response,
    encode_server_rejection,
    make_mask_key,
    parse_close_payload,
    validate_text_payload,
)

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    """Every concrete exception subclasses :class:`WebSocketError`."""

    def test_all_concrete_exceptions_inherit_base(self):
        from chumicro_websockets import (
            WebSocketBackpressureError,
            WebSocketStateError,
            WebSocketTimeoutError,
        )
        from chumicro_websockets import (
            WebSocketHandshakeError as HandshakeError,
        )
        from chumicro_websockets import (
            WebSocketProtocolError as ProtocolError,
        )
        from chumicro_websockets import (
            WebSocketURLError as URLError,
        )

        assert issubclass(ProtocolError, WebSocketError)
        assert issubclass(HandshakeError, WebSocketError)
        assert issubclass(URLError, WebSocketError)
        assert issubclass(WebSocketTimeoutError, WebSocketError)
        assert issubclass(WebSocketBackpressureError, WebSocketError)
        assert issubclass(WebSocketStateError, WebSocketError)


# ---------------------------------------------------------------------------
# CaseInsensitiveDict
# ---------------------------------------------------------------------------


class TestCaseInsensitiveDict:
    """Header dict folds names to lowercase but preserves original case on iter."""

    def test_set_and_get_case_insensitive(self):
        headers = CaseInsensitiveDict()
        headers["Upgrade"] = "websocket"
        assert headers["upgrade"] == "websocket"
        assert headers["UPGRADE"] == "websocket"

    def test_contains_case_insensitive(self):
        headers = CaseInsensitiveDict()
        headers["Sec-WebSocket-Key"] = "abc"
        assert "sec-websocket-key" in headers
        assert "SEC-WEBSOCKET-KEY" in headers

    def test_get_with_default(self):
        headers = CaseInsensitiveDict()
        assert headers.get("missing") is None
        assert headers.get("missing", "default") == "default"

    def test_items_yields_original_pairs(self):
        headers = CaseInsensitiveDict()
        headers["Upgrade"] = "websocket"
        items = list(headers.items())
        assert items == [("Upgrade", "websocket")]

    def test_items_preserves_insertion_order(self):
        headers = CaseInsensitiveDict()
        headers["Host"] = "example.com"
        headers["Upgrade"] = "websocket"
        headers["Connection"] = "Upgrade"
        headers["Sec-WebSocket-Key"] = "dGhlIHNhbXBsZSBub25jZQ=="
        headers["Sec-WebSocket-Version"] = "13"
        names = [name for name, _ in headers.items()]
        assert names == [
            "Host", "Upgrade", "Connection",
            "Sec-WebSocket-Key", "Sec-WebSocket-Version",
        ]

    def test_overwrite_preserves_original_position(self):
        headers = CaseInsensitiveDict()
        headers["Host"] = "first.com"
        headers["Upgrade"] = "websocket"
        headers["host"] = "second.com"
        items = list(headers.items())
        assert items == [("host", "second.com"), ("Upgrade", "websocket")]

    def test_getitem_raises_keyerror_on_missing(self):
        headers = CaseInsensitiveDict()
        with raises(KeyError):
            headers["missing"]


# ---------------------------------------------------------------------------
# parse_ws_url
# ---------------------------------------------------------------------------


class TestParseWsUrl:
    """``ws://`` and ``wss://`` parse to ``(scheme, host, port, path)``."""

    def test_ws_default_port(self):
        assert parse_ws_url("ws://example.com/") == ("ws", "example.com", 80, "/")

    def test_wss_default_port(self):
        assert parse_ws_url("wss://example.com/") == (
            "wss",
            "example.com",
            443,
            "/",
        )

    def test_explicit_port(self):
        assert parse_ws_url("ws://example.com:8080/") == (
            "ws",
            "example.com",
            8080,
            "/",
        )

    def test_path_with_query(self):
        assert parse_ws_url("ws://example.com/path?q=1") == (
            "ws",
            "example.com",
            80,
            "/path?q=1",
        )

    def test_no_path_defaults_to_slash(self):
        assert parse_ws_url("ws://example.com") == ("ws", "example.com", 80, "/")

    def test_no_path_with_explicit_port(self):
        assert parse_ws_url("wss://api.host:8443") == (
            "wss",
            "api.host",
            8443,
            "/",
        )

    def test_non_string_raises(self):
        with raises(WebSocketURLError, match="must be str"):
            parse_ws_url(b"ws://example.com/")

    def test_unsupported_scheme_raises(self):
        with raises(WebSocketURLError, match="ws:// or wss://"):
            parse_ws_url("http://example.com/")

    def test_missing_host_raises(self):
        with raises(WebSocketURLError, match="missing host"):
            parse_ws_url("ws://")

    def test_missing_host_before_path_raises(self):
        with raises(WebSocketURLError, match="missing host"):
            parse_ws_url("ws:///path")

    def test_missing_host_before_port_raises(self):
        with raises(WebSocketURLError, match="missing host"):
            parse_ws_url("ws://:8080/")

    def test_non_integer_port_raises(self):
        with raises(WebSocketURLError, match="non-integer port"):
            parse_ws_url("ws://h:abc/")

    def test_port_out_of_range_zero_raises(self):
        with raises(WebSocketURLError, match="out of range"):
            parse_ws_url("ws://h:0/")

    def test_port_out_of_range_high_raises(self):
        with raises(WebSocketURLError, match="out of range"):
            parse_ws_url("ws://h:99999/")


# ---------------------------------------------------------------------------
# Sec-WebSocket-Key + Sec-WebSocket-Accept derivation
# ---------------------------------------------------------------------------


# TestSha1Dispatch lives in test_websockets_pytest.py — it simulates
# the CP fallback path by deleting ``hashlib.sha1`` and exercising the
# ``hashlib.new("sha1", ...)`` branch, but MP / CP unix-ports lack
# ``hashlib.new`` so the fallback can't be exercised on them.  The
# real fast-path (``hashlib.sha1`` present) is exercised by every
# other handshake test in this file.


class TestKeyDerivation:
    """RFC 6455 §1.3 and §4.2.2 worked examples."""

    def test_make_websocket_key_is_base64_22_chars(self):
        # 16 raw bytes -> 22 base64 chars + '==' padding -> 24 chars total.
        key = make_websocket_key()
        assert len(key) == 24
        assert key.endswith("==")
        # Distinct keys per call.
        assert make_websocket_key() != key

    def test_derive_accept_known_vector(self):
        # RFC 6455 §1.3 worked example: client key
        # "dGhlIHNhbXBsZSBub25jZQ==" yields accept token
        # "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=".
        assert derive_accept_key("dGhlIHNhbXBsZSBub25jZQ==") == (
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        )

    def test_magic_guid_constant(self):
        assert WS_MAGIC_GUID == "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ---------------------------------------------------------------------------
# encode_client_handshake
# ---------------------------------------------------------------------------


class TestEncodeClientHandshake:
    """Client opening handshake produces a well-formed HTTP/1.1 GET."""

    def test_default_port_omitted_from_host(self):
        encoded = encode_client_handshake(
            "example.com",
            80,
            "/",
            "dGhlIHNhbXBsZSBub25jZQ==",
        )
        assert b"Host: example.com\r\n" in encoded
        assert b":80" not in encoded

    def test_non_default_port_included_in_host(self):
        encoded = encode_client_handshake(
            "example.com",
            8080,
            "/path",
            "dGhlIHNhbXBsZSBub25jZQ==",
        )
        assert b"Host: example.com:8080\r\n" in encoded

    def test_required_upgrade_headers_present(self):
        encoded = encode_client_handshake(
            "example.com",
            80,
            "/",
            "dGhlIHNhbXBsZSBub25jZQ==",
        )
        assert b"GET / HTTP/1.1\r\n" in encoded
        assert b"Upgrade: websocket\r\n" in encoded
        assert b"Connection: Upgrade\r\n" in encoded
        assert b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n" in encoded
        assert b"Sec-WebSocket-Version: 13\r\n" in encoded
        assert encoded.endswith(b"\r\n\r\n")

    def test_extra_headers_merged_dict(self):
        encoded = encode_client_handshake(
            "example.com",
            80,
            "/",
            "dGhlIHNhbXBsZSBub25jZQ==",
            extra_headers={"Origin": "https://app.example.com"},
        )
        assert b"Origin: https://app.example.com\r\n" in encoded

    def test_extra_headers_merged_iterable(self):
        encoded = encode_client_handshake(
            "example.com",
            80,
            "/",
            "dGhlIHNhbXBsZSBub25jZQ==",
            extra_headers=[("Cookie", "session=abc")],
        )
        assert b"Cookie: session=abc\r\n" in encoded

    def test_extra_headers_merged_caseinsensitivedict(self):
        extras = CaseInsensitiveDict()
        extras["Authorization"] = "Bearer token"
        encoded = encode_client_handshake(
            "example.com",
            80,
            "/",
            "dGhlIHNhbXBsZSBub25jZQ==",
            extra_headers=extras,
        )
        assert b"Authorization: Bearer token\r\n" in encoded

    def test_caller_cannot_override_required_upgrade_headers(self):
        encoded = encode_client_handshake(
            "example.com",
            80,
            "/",
            "dGhlIHNhbXBsZSBub25jZQ==",
            extra_headers={"Upgrade": "h2c"},
        )
        # Mandatory header wins — we don't ship "Upgrade: h2c".
        assert b"Upgrade: websocket\r\n" in encoded
        assert b"Upgrade: h2c\r\n" not in encoded

    def test_path_with_query_string_preserved(self):
        encoded = encode_client_handshake(
            "example.com",
            80,
            "/socket?token=xyz",
            "dGhlIHNhbXBsZSBub25jZQ==",
        )
        assert b"GET /socket?token=xyz HTTP/1.1\r\n" in encoded


# ---------------------------------------------------------------------------
# encode_server_handshake_response
# ---------------------------------------------------------------------------


class TestEncodeServerHandshakeResponse:
    """Server's 101 response derives accept token + adds upgrade headers."""

    def test_status_line_is_101(self):
        encoded = encode_server_handshake_response("dGhlIHNhbXBsZSBub25jZQ==")
        assert encoded.startswith(b"HTTP/1.1 101 Switching Protocols\r\n")

    def test_required_headers_present(self):
        encoded = encode_server_handshake_response("dGhlIHNhbXBsZSBub25jZQ==")
        assert b"Upgrade: websocket\r\n" in encoded
        assert b"Connection: Upgrade\r\n" in encoded
        assert b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n" in encoded
        assert encoded.endswith(b"\r\n\r\n")

    def test_extra_headers_dict_merged(self):
        encoded = encode_server_handshake_response(
            "dGhlIHNhbXBsZSBub25jZQ==",
            extra_headers={"X-Server": "chumicro"},
        )
        assert b"X-Server: chumicro\r\n" in encoded

    def test_extra_headers_iterable_merged(self):
        encoded = encode_server_handshake_response(
            "dGhlIHNhbXBsZSBub25jZQ==",
            extra_headers=[("X-Server", "chumicro")],
        )
        assert b"X-Server: chumicro\r\n" in encoded

    def test_extra_headers_caseinsensitivedict_merged(self):
        extras = CaseInsensitiveDict()
        extras["X-Custom"] = "value"
        encoded = encode_server_handshake_response(
            "dGhlIHNhbXBsZSBub25jZQ==",
            extra_headers=extras,
        )
        assert b"X-Custom: value\r\n" in encoded

    def test_required_headers_win_over_caller_overrides(self):
        encoded = encode_server_handshake_response(
            "dGhlIHNhbXBsZSBub25jZQ==",
            extra_headers={"Upgrade": "h2c"},
        )
        assert b"Upgrade: websocket\r\n" in encoded
        assert b"Upgrade: h2c\r\n" not in encoded


# ---------------------------------------------------------------------------
# encode_server_rejection
# ---------------------------------------------------------------------------


class TestEncodeServerRejection:
    """Non-101 HTTP error responses for invalid upgrade requests."""

    def test_status_and_reason(self):
        encoded = encode_server_rejection(404, "Not Found")
        assert encoded.startswith(b"HTTP/1.1 404 Not Found\r\n")

    def test_connection_close_is_added(self):
        encoded = encode_server_rejection(400, "Bad Request")
        assert b"Connection: close\r\n" in encoded

    def test_no_body_no_content_length(self):
        encoded = encode_server_rejection(400, "Bad Request")
        assert b"Content-Length" not in encoded

    def test_body_adds_content_length_and_type(self):
        encoded = encode_server_rejection(
            400,
            "Bad Request",
            body=b"missing upgrade header",
        )
        assert b"Content-Length: 22\r\n" in encoded
        assert b"Content-Type: text/plain; charset=utf-8\r\n" in encoded
        assert encoded.endswith(b"missing upgrade header")

    def test_custom_content_type(self):
        encoded = encode_server_rejection(
            400,
            "Bad Request",
            body=b'{"error": "bad"}',
            content_type="application/json",
        )
        assert b"Content-Type: application/json\r\n" in encoded


# ---------------------------------------------------------------------------
# HandshakeResponseParser
# ---------------------------------------------------------------------------


class TestHandshakeResponseParser:
    """Client side: validates the 101 response."""

    EXPECTED_ACCEPT = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="

    def _good_response(self, *, extra_headers=b"") -> bytes:
        return (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + self.EXPECTED_ACCEPT.encode("ascii") + b"\r\n"
            + extra_headers
            + b"\r\n"
        )

    def test_well_formed_response_reaches_done(self):
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        parser.feed(self._good_response())
        assert parser.state == HandshakeParseState.DONE
        assert parser.status_code == 101
        assert parser.reason == "Switching Protocols"
        assert parser.http_version == "HTTP/1.1"
        assert parser.headers["Upgrade"] == "websocket"
        assert parser.error is None

    def test_byte_at_a_time_streaming(self):
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        for byte_value in self._good_response():
            parser.feed(bytes([byte_value]))
        assert parser.state == HandshakeParseState.DONE

    def test_leftover_bytes_after_terminator_kept(self):
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        parser.feed(self._good_response() + b"\x81\x05hello")
        assert parser.state == HandshakeParseState.DONE
        assert parser.leftover == b"\x81\x05hello"

    def test_non_101_status_raises(self):
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        with raises(WebSocketHandshakeError, match="404"):
            parser.feed(b"HTTP/1.1 404 Not Found\r\n\r\n")
        assert parser.state == HandshakeParseState.ERROR

    def test_malformed_status_line_raises(self):
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        with raises(WebSocketHandshakeError, match="malformed status"):
            parser.feed(b"HTTP/1.1\r\n\r\n")

    def test_non_integer_status_raises(self):
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        with raises(WebSocketHandshakeError, match="non-integer status"):
            parser.feed(b"HTTP/1.1 OK Oops\r\n\r\n")

    def test_non_ascii_status_line_raises(self):
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        with raises(WebSocketHandshakeError, match="non-ASCII"):
            parser.feed(b"HTTP/1.1 101 \xe9\r\n\r\n")

    def test_missing_upgrade_header_raises(self):
        bad = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + self.EXPECTED_ACCEPT.encode("ascii") + b"\r\n"
            b"\r\n"
        )
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        with raises(WebSocketHandshakeError, match="Upgrade: websocket"):
            parser.feed(bad)

    def test_missing_connection_header_raises(self):
        bad = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Sec-WebSocket-Accept: " + self.EXPECTED_ACCEPT.encode("ascii") + b"\r\n"
            b"\r\n"
        )
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        with raises(WebSocketHandshakeError, match="Connection: Upgrade"):
            parser.feed(bad)

    def test_wrong_accept_raises(self):
        bad = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: wrong-value\r\n"
            b"\r\n"
        )
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        with raises(WebSocketHandshakeError, match="Accept mismatch"):
            parser.feed(bad)

    def test_header_without_colon_raises(self):
        bad = b"HTTP/1.1 101 OK\r\nNoColonHere\r\n\r\n"
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        with raises(WebSocketHandshakeError, match="missing colon"):
            parser.feed(bad)

    def test_empty_header_name_raises(self):
        bad = b"HTTP/1.1 101 OK\r\n: value\r\n\r\n"
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        with raises(WebSocketHandshakeError, match="empty header name"):
            parser.feed(bad)

    def test_oversize_buffer_raises(self):
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT, max_header_bytes=20)
        with raises(WebSocketHandshakeError, match="max_header_bytes"):
            parser.feed(b"HTTP/1.1 101 OK\r\nX-Long: " + b"a" * 100)

    def test_feeding_after_done_is_noop(self):
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        parser.feed(self._good_response())
        # Should not raise.
        parser.feed(b"more bytes")
        assert parser.state == HandshakeParseState.DONE

    def test_feeding_after_error_is_noop(self):
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        with raises(WebSocketHandshakeError):
            parser.feed(b"HTTP/1.1 500 Server Error\r\n\r\n")
        # Already in ERROR — second feed must not raise again or advance.
        parser.feed(b"more")
        assert parser.state == HandshakeParseState.ERROR

    def test_connection_keep_alive_token_rejected(self):
        # 'Connection: keep-alive' does NOT contain the 'upgrade' token.
        bad = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: keep-alive\r\n"
            b"Sec-WebSocket-Accept: " + self.EXPECTED_ACCEPT.encode("ascii") + b"\r\n"
            b"\r\n"
        )
        parser = HandshakeResponseParser(self.EXPECTED_ACCEPT)
        with raises(WebSocketHandshakeError, match="Connection: Upgrade"):
            parser.feed(bad)


# ---------------------------------------------------------------------------
# HandshakeRequestParser
# ---------------------------------------------------------------------------


class TestHandshakeRequestParser:
    """Server side: validates the client's upgrade GET."""

    GOOD_KEY = "dGhlIHNhbXBsZSBub25jZQ=="

    def _good_request(self, *, key=None, extra_headers=b"") -> bytes:
        used_key = key or self.GOOD_KEY
        return (
            b"GET /chat HTTP/1.1\r\n"
            b"Host: server.example.com\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Key: " + used_key.encode("ascii") + b"\r\n"
            b"Sec-WebSocket-Version: 13\r\n"
            + extra_headers
            + b"\r\n"
        )

    def test_well_formed_request_reaches_done(self):
        parser = HandshakeRequestParser()
        parser.feed(self._good_request())
        assert parser.state == HandshakeParseState.DONE
        assert parser.method == "GET"
        assert parser.path == "/chat"
        assert parser.http_version == "HTTP/1.1"
        assert parser.client_key == self.GOOD_KEY
        assert parser.error is None

    def test_byte_at_a_time(self):
        parser = HandshakeRequestParser()
        for byte_value in self._good_request():
            parser.feed(bytes([byte_value]))
        assert parser.state == HandshakeParseState.DONE

    def test_leftover_bytes_kept(self):
        parser = HandshakeRequestParser()
        parser.feed(self._good_request() + b"FRAMEBYTES")
        assert parser.leftover == b"FRAMEBYTES"

    def test_post_method_rejected(self):
        bad = self._good_request().replace(b"GET ", b"POST ", 1)
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="method must be GET"):
            parser.feed(bad)

    def test_http_2_rejected(self):
        bad = self._good_request().replace(b"HTTP/1.1\r\n", b"HTTP/2.0\r\n", 1)
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="HTTP/1.1"):
            parser.feed(bad)

    def test_malformed_request_line_rejected(self):
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="malformed request"):
            parser.feed(b"GETONLY\r\n\r\n")

    def test_non_ascii_request_line_rejected(self):
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="non-ASCII"):
            parser.feed(b"GET /\xe9 HTTP/1.1\r\n\r\n")

    def test_missing_upgrade_rejected(self):
        bad = self._good_request().replace(b"Upgrade: websocket\r\n", b"")
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="Upgrade: websocket"):
            parser.feed(bad)

    def test_missing_connection_rejected(self):
        bad = self._good_request().replace(b"Connection: Upgrade\r\n", b"")
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="Connection: Upgrade"):
            parser.feed(bad)

    def test_wrong_version_rejected(self):
        bad = self._good_request().replace(
            b"Sec-WebSocket-Version: 13\r\n",
            b"Sec-WebSocket-Version: 8\r\n",
        )
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="Sec-WebSocket-Version"):
            parser.feed(bad)

    def test_missing_key_rejected(self):
        bad = self._good_request().replace(
            b"Sec-WebSocket-Key: " + self.GOOD_KEY.encode("ascii") + b"\r\n",
            b"",
        )
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="Sec-WebSocket-Key"):
            parser.feed(bad)

    def test_invalid_base64_key_rejected(self):
        bad = self._good_request(key="!!!notbase64!!!")
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="not valid base64"):
            parser.feed(bad)

    def test_wrong_length_key_rejected(self):
        # base64("abc") = "YWJj" decodes to 3 bytes, not 16.
        bad = self._good_request(key="YWJj")
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="16 bytes"):
            parser.feed(bad)

    def test_header_without_colon_rejected(self):
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="missing colon"):
            parser.feed(b"GET / HTTP/1.1\r\nNoColonHere\r\n\r\n")

    def test_empty_header_name_rejected(self):
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="empty header name"):
            parser.feed(b"GET / HTTP/1.1\r\n: value\r\n\r\n")

    def test_oversize_buffer_rejected(self):
        parser = HandshakeRequestParser(max_header_bytes=20)
        with raises(WebSocketHandshakeError, match="max_header_bytes"):
            parser.feed(b"GET / HTTP/1.1\r\nX-Long: " + b"a" * 100)

    def test_feed_after_done_is_noop(self):
        parser = HandshakeRequestParser()
        parser.feed(self._good_request())
        parser.feed(b"more")  # must not raise
        assert parser.state == HandshakeParseState.DONE

    def test_feed_after_error_is_noop(self):
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError):
            parser.feed(b"POST / HTTP/1.1\r\n\r\n")
        parser.feed(b"more")
        assert parser.state == HandshakeParseState.ERROR

    def test_connection_keep_alive_rejected(self):
        bad = self._good_request().replace(
            b"Connection: Upgrade\r\n",
            b"Connection: keep-alive\r\n",
        )
        parser = HandshakeRequestParser()
        with raises(WebSocketHandshakeError, match="Connection: Upgrade"):
            parser.feed(bad)

    def test_headers_accessor_exposes_parsed_headers(self):
        parser = HandshakeRequestParser()
        parser.feed(self._good_request())
        assert isinstance(parser.headers, CaseInsensitiveDict)
        assert parser.headers["Host"] == "server.example.com"
        assert parser.headers["Upgrade"] == "websocket"


# ---------------------------------------------------------------------------
# FrameParser — happy path
# ---------------------------------------------------------------------------


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
        # Client → server: MASK=1, mask=b"mask", len=4, payload="ping" XOR mask.
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
        # with a small payload — the length-byte parsing path matters more
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

    def test_consumed_count_stops_at_frame_boundary(self):
        # Feed two back-to-back frames; first call should consume only frame 1.
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
        # FIN=0 + CONT is valid mid-fragmentation; parser doesn't enforce
        # message-level rules (that's the client/server's job).
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


# ---------------------------------------------------------------------------
# FrameParser — error paths
# ---------------------------------------------------------------------------


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
        # PING with 126-byte payload — uses the 16-bit length form which
        # itself is illegal for control frames.
        parser = FrameParser()
        with raises(WebSocketProtocolError, match="125"):
            parser.feed(b"\x89\x7e" + struct.pack("!H", 126))

    def test_payload_over_max_raises(self):
        parser = FrameParser(max_payload_bytes=100)
        with raises(WebSocketProtocolError, match="max_payload_bytes"):
            parser.feed(b"\x82\x7e" + struct.pack("!H", 500))

    def test_payload_over_max_via_64bit_length_raises(self):
        parser = FrameParser(max_payload_bytes=100)
        with raises(WebSocketProtocolError, match="max_payload_bytes"):
            parser.feed(b"\x82\x7f" + struct.pack("!Q", 1 << 40))

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


# ---------------------------------------------------------------------------
# encode_frame
# ---------------------------------------------------------------------------


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

    def test_make_mask_key_length(self):
        assert len(make_mask_key()) == 4
        # Non-deterministic, but two calls almost surely differ.
        assert make_mask_key() != make_mask_key()


# ---------------------------------------------------------------------------
# Close payload codec
# ---------------------------------------------------------------------------


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


class TestParseClosePayload:
    """Close-frame body decoder."""

    def test_empty_payload(self):
        assert parse_close_payload(b"") == (None, "")

    def test_one_byte_payload_rejected(self):
        with raises(WebSocketProtocolError, match="1 byte"):
            parse_close_payload(b"\x03")

    def test_code_and_reason(self):
        body = struct.pack("!H", CLOSE_GOING_AWAY) + b"bye"
        assert parse_close_payload(body) == (CLOSE_GOING_AWAY, "bye")

    def test_code_only(self):
        body = struct.pack("!H", CLOSE_NORMAL)
        assert parse_close_payload(body) == (CLOSE_NORMAL, "")

    def test_reserved_code_rejected(self):
        body = struct.pack("!H", CLOSE_ABNORMAL)
        with raises(WebSocketProtocolError, match="reserved"):
            parse_close_payload(body)

    def test_invalid_utf8_reason_rejected(self):
        body = struct.pack("!H", CLOSE_NORMAL) + b"\xff\xfe"
        with raises(WebSocketProtocolError, match="UTF-8"):
            parse_close_payload(body)


# ---------------------------------------------------------------------------
# validate_text_payload
# ---------------------------------------------------------------------------


class TestValidateTextPayload:
    """RFC 6455 §8.1 — text frames MUST be valid UTF-8."""

    def test_ascii_passes(self):
        assert validate_text_payload(b"hello") == "hello"

    def test_multibyte_utf8_passes(self):
        # Snowman, 3 bytes UTF-8.
        assert validate_text_payload(b"\xe2\x98\x83") == "☃"

    def test_invalid_utf8_raises(self):
        with raises(WebSocketProtocolError, match="UTF-8"):
            validate_text_payload(b"\xff\xfe")


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


class TestConstants:
    """Constant values match spec."""

    def test_ws_version(self):
        assert WS_VERSION == "13"

    def test_max_control_payload(self):
        assert MAX_CONTROL_PAYLOAD_BYTES == 125

    def test_default_max_message_bytes(self):
        assert DEFAULT_MAX_MESSAGE_BYTES == 16384

    def test_close_codes(self):
        assert CLOSE_NORMAL == 1000
        assert CLOSE_PROTOCOL_ERROR == 1002
        assert CLOSE_BAD_DATA == 1007

    def test_state_constants(self):
        assert WebSocketState.CONNECTING == "connecting"
        assert WebSocketState.OPEN == "open"
        assert WebSocketState.CLOSING == "closing"
        assert WebSocketState.CLOSED == "closed"

    def test_opcode_categories(self):
        from chumicro_websockets._wire import CONTROL_OPCODES, DATA_OPCODES

        assert OPCODE_TEXT in DATA_OPCODES
        assert OPCODE_BINARY in DATA_OPCODES
        assert OPCODE_CONTINUATION in DATA_OPCODES
        assert OPCODE_PING in CONTROL_OPCODES
        assert OPCODE_PONG in CONTROL_OPCODES
        assert OPCODE_CLOSE in CONTROL_OPCODES
