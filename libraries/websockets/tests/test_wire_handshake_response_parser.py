"""Wire tests for chumicro_websockets._wire: streaming
HandshakeResponseParser."""

from chumicro_test_harness.assertions import raises
from chumicro_websockets import WebSocketHandshakeError
from chumicro_websockets._wire import (
    HandshakeParseState,
    HandshakeResponseParser,
)


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
