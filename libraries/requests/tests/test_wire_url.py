"""Wire-format tests for chumicro_requests — URL parsing, Content-Type
charset parsing, and redirect URL resolution.
"""

from chumicro_requests import (
    HttpURLError,
    parse_charset,
    parse_url,
    resolve_redirect_url,
)
from chumicro_test_harness.assertions import raises

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

    def test_query_without_path_terminates_authority(self):
        # '?' ends the authority: the query must not fold into the host.
        assert parse_url("http://example.com?key=abc") == (
            "http", "example.com", 80, "/?key=abc",
        )

    def test_query_without_path_with_explicit_port(self):
        # '?' ends the authority before the port is misparsed.
        assert parse_url("http://example.com:8080?q=1") == (
            "http", "example.com", 8080, "/?q=1",
        )

    def test_fragment_without_path_terminates_authority(self):
        assert parse_url("http://example.com#frag") == (
            "http", "example.com", 80, "/#frag",
        )

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
