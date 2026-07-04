"""Wire-format tests for chumicro_requests — case-insensitive header dict
and request encoding.
"""

from chumicro_requests import (
    CaseInsensitiveDict,
    HttpURLError,
    encode_request,
)
from chumicro_test_harness.assertions import raises

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

    def test_non_ascii_in_header_value_rejected(self):
        # A non-ASCII header value would encode as UnicodeEncodeError on
        # CPython but as silent UTF-8 bytes on MicroPython; reject it so
        # the failure is one catchable HttpURLError on every runtime.
        with raises(HttpURLError, match="non-ASCII"):
            encode_request("GET", "h", "/", headers={"X-Note": "café"})

    def test_non_ascii_in_path_rejected(self):
        with raises(HttpURLError, match="non-ASCII"):
            encode_request("GET", "h", "/naïve")

    def test_non_ascii_in_header_name_rejected(self):
        with raises(HttpURLError, match="non-ASCII"):
            encode_request("GET", "h", "/", headers={"X-Ünë": "v"})

    def test_ascii_header_value_still_encodes(self):
        # Plain ASCII passes the guard and reaches the wire unchanged.
        request_bytes = encode_request(
            "GET", "h", "/", headers={"X-Note": "plain-value"},
        )
        assert b"X-Note: plain-value\r\n" in request_bytes
