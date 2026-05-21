"""Wire tests for chumicro_websockets._wire: exception hierarchy,
CaseInsensitiveDict, parse_ws_url."""

from chumicro_test_harness.assertions import raises
from chumicro_websockets import (
    WebSocketError,
    WebSocketURLError,
    parse_ws_url,
)
from chumicro_websockets._wire import CaseInsensitiveDict


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
