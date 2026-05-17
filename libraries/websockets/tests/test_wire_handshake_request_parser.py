"""Wire tests for chumicro_websockets._wire: streaming
HandshakeRequestParser."""

from chumicro_test_harness.assertions import raises
from chumicro_websockets import WebSocketHandshakeError
from chumicro_websockets._wire import (
    CaseInsensitiveDict,
    HandshakeParseState,
    HandshakeRequestParser,
)


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
