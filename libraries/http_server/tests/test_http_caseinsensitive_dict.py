"""http_server: CaseInsensitiveDict header map."""

from chumicro_http_server import CaseInsensitiveDict


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
        # Returning NotImplemented makes Python fall back; against a
        # plain dict both sides return NotImplemented and Python settles
        # on False.
        assert headers != {"a": 1}

    def test_repr_round_trip_keys(self):
        headers = CaseInsensitiveDict()
        headers["A"] = "1"
        headers["B"] = "2"
        text = repr(headers)
        assert "A" in text and "B" in text
