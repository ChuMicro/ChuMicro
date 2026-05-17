"""Wire tests for chumicro_websockets._wire: key derivation and the
client / server opening-handshake encoders."""

from chumicro_websockets import (
    derive_accept_key,
    make_websocket_key,
)
from chumicro_websockets._wire import (
    WS_MAGIC_GUID,
    CaseInsensitiveDict,
    encode_client_handshake,
    encode_server_handshake_response,
    encode_server_rejection,
)


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
