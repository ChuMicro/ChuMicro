"""requests client: Response decode — .encoding / .text / .json()."""

from chumicro_requests import (
    CaseInsensitiveDict,
    Response,
)
from chumicro_test_harness.assertions import raises


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
        with raises(ValueError):
            response.json()

    def test_text_decode_error_propagates(self):
        # Latin-1-only byte that's invalid UTF-8.
        response = self._make(body=b"\xff", content_type="text/plain; charset=utf-8")
        with raises(UnicodeError):
            _ = response.text
