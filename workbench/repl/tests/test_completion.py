"""Tests for tab completion."""

from __future__ import annotations

import pytest
from chumicro_repl.completion import (
    STATIC_CATALOG,
    CombinedCompleter,
    CompletionCache,
    DeviceCompleter,
    KeywordCompleter,
    PromptToolkitCompleter,
    _completable_tail,
    _parse_dir_response,
    build_default_completer,
    fetch_device_names,
)
from chumicro_repl.testing import FakeSerialPort, FakeTime


class TestCompletableTail:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("pri", "pri"),
            ("x = pri", "pri"),
            ("foo()", ""),
            ("x.y", "y"),
            ("range(", ""),
            ("for i in r", "r"),
            ("", ""),
            ("123", ""),  # leading digit isn't a Python identifier
            ("foo_bar", "foo_bar"),
        ],
    )
    def test_extracts_trailing_identifier(self, text: str, expected: str) -> None:
        assert _completable_tail(text) == expected


class TestKeywordCompleter:
    def test_static_catalog_includes_python_keywords(self) -> None:
        # `import` is in `keyword.kwlist`; `print` is in builtins.
        assert "import" in STATIC_CATALOG
        assert "print" in STATIC_CATALOG
        assert "range" in STATIC_CATALOG
        assert "True" in STATIC_CATALOG

    def test_dunders_excluded(self) -> None:
        # Public API should not surface `__import__`, `__name__`, etc.
        assert "__import__" not in STATIC_CATALOG
        assert "__build_class__" not in STATIC_CATALOG

    def test_empty_prefix_returns_full_catalog(self) -> None:
        completer = KeywordCompleter()
        candidates = list(completer.candidates(""))
        assert sorted(candidates) == sorted(STATIC_CATALOG)

    def test_prefix_filters(self) -> None:
        completer = KeywordCompleter()
        result = list(completer.candidates("pri"))
        assert "print" in result
        assert "import" not in result
        # Every result begins with the prefix.
        for candidate in result:
            assert candidate.startswith("pri")

    def test_custom_catalog(self) -> None:
        completer = KeywordCompleter(["alpha", "beta", "gamma"])
        assert list(completer.candidates("a")) == ["alpha"]
        assert list(completer.candidates("g")) == ["gamma"]
        assert sorted(completer.candidates("")) == ["alpha", "beta", "gamma"]


class TestCompletionCache:
    def test_get_missing_returns_none(self) -> None:
        cache = CompletionCache()
        assert cache.get("") is None
        assert cache.get("foo") is None

    def test_put_then_get_round_trip(self) -> None:
        cache = CompletionCache()
        cache.put("", ["alpha", "beta", "alpha"])
        # Stored deduplicated + sorted.
        assert cache.get("") == ("alpha", "beta")

    def test_clear_drops_everything(self) -> None:
        cache = CompletionCache()
        cache.put("", ["a"])
        cache.put("foo", ["b"])
        cache.clear()
        assert cache.get("") is None
        assert cache.get("foo") is None

    def test_get_after_put(self) -> None:
        cache = CompletionCache()
        assert cache.get("") is None
        cache.put("", ["a"])
        assert cache.get("") == ("a",)


class TestDeviceCompleter:
    def test_no_fetcher_returns_empty(self) -> None:
        completer = DeviceCompleter()
        assert list(completer.candidates("")) == []
        assert list(completer.candidates("foo")) == []

    def test_fetcher_called_once_per_namespace(self) -> None:
        calls: list[str] = []

        def fetcher(expression: str):
            calls.append(expression)
            return ["foo", "bar", "baz"]

        completer = DeviceCompleter(fetcher=fetcher)
        # First Tab triggers the fetch.
        first = list(completer.candidates(""))
        assert sorted(first) == ["bar", "baz", "foo"]
        # Second Tab hits the cache — no additional fetch call.
        list(completer.candidates("ba"))
        assert calls == [""]

    def test_fetcher_returning_none_no_cache(self) -> None:
        """A timeout-shape failure shouldn't poison the cache forever."""
        call_count = [0]

        def flaky_fetcher(_expression: str):
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # first attempt fails
            return ["recovered"]

        completer = DeviceCompleter(fetcher=flaky_fetcher)
        # First Tab returns nothing.
        assert list(completer.candidates("")) == []
        # Second Tab retries and populates the cache.
        assert list(completer.candidates("")) == ["recovered"]

    def test_prefix_filters_cached_candidates(self) -> None:
        completer = DeviceCompleter(
            fetcher=lambda _: ["alpha", "anchor", "beta"],
        )
        result = list(completer.candidates("a"))
        assert sorted(result) == ["alpha", "anchor"]

    def test_explicit_cache_invalidation(self) -> None:
        """The CompletionCache exposed via .cache lets callers invalidate on reset."""
        call_count = [0]

        def fetcher(_expression: str):
            call_count[0] += 1
            return [f"snapshot_{call_count[0]}"]

        completer = DeviceCompleter(fetcher=fetcher)
        list(completer.candidates(""))
        assert call_count[0] == 1
        completer.cache.clear()
        list(completer.candidates(""))
        # Re-fetched after cache clear.
        assert call_count[0] == 2


class TestCombinedCompleter:
    def test_dedup_across_sources(self) -> None:
        first = KeywordCompleter(["alpha", "shared"])
        second = KeywordCompleter(["beta", "shared"])
        combined = CombinedCompleter([first, second])
        assert list(combined.candidates("")) == ["alpha", "beta", "shared"]

    def test_prefix_applied_to_each_source(self) -> None:
        first = KeywordCompleter(["alpha", "anchor"])
        second = KeywordCompleter(["beta", "auspicious"])
        combined = CombinedCompleter([first, second])
        result = list(combined.candidates("a"))
        # Both "alpha"/"anchor" and "auspicious" pass the prefix.
        assert sorted(result) == ["alpha", "anchor", "auspicious"]

    def test_empty_sources(self) -> None:
        assert list(CombinedCompleter([]).candidates("")) == []


class TestPromptToolkitAdapter:
    def test_get_completions_yields_completion_objects(self) -> None:
        pytest.importorskip("prompt_toolkit")
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document

        source = KeywordCompleter(["alpha", "anchor", "beta"])
        adapter = PromptToolkitCompleter(source)
        document = Document("a", cursor_position=1)
        event = CompleteEvent()
        results = list(adapter.get_completions(document, event))
        texts = [completion.text for completion in results]
        assert sorted(texts) == ["alpha", "anchor"]
        # start_position lets prompt_toolkit replace the partial token.
        assert all(completion.start_position == -1 for completion in results)

    def test_empty_prefix_completes_full_catalog(self) -> None:
        pytest.importorskip("prompt_toolkit")
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document

        source = KeywordCompleter(["alpha", "beta"])
        adapter = PromptToolkitCompleter(source)
        document = Document("", cursor_position=0)
        results = list(adapter.get_completions(document, CompleteEvent()))
        assert sorted(item.text for item in results) == ["alpha", "beta"]


class TestBuildDefaultCompleter:
    def test_returns_prompt_toolkit_compatible(self) -> None:
        pytest.importorskip("prompt_toolkit")
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document

        completer = build_default_completer()
        document = Document("pri", cursor_position=3)
        # Sanity — adapter exposes get_completions and yields `Completion` objects.
        results = list(completer.get_completions(document, CompleteEvent()))  # type: ignore[attr-defined]
        texts = [completion.text for completion in results]
        assert "print" in texts

    def test_with_port_wires_device_completer(self) -> None:
        pytest.importorskip("prompt_toolkit")
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document

        port = FakeSerialPort(read_chunks=[
            b"raw REPL; CTRL-B to exit\r\n>",
            b"OK['foo_device', 'bar_device']\n\x04\x04>",
            b"\r\nMicroPython v1.28.0\r\n>>> ",
        ])
        completer = build_default_completer(port=port, time=FakeTime())
        document = Document("foo_d", cursor_position=5)
        results = list(completer.get_completions(document, CompleteEvent()))  # type: ignore[attr-defined]
        texts = [completion.text for completion in results]
        assert "foo_device" in texts
        # Static catalog still merges in for keyword-prefix tabs.
        document = Document("pri", cursor_position=3)
        results = list(completer.get_completions(document, CompleteEvent()))  # type: ignore[attr-defined]
        assert "print" in [completion.text for completion in results]

    def test_caller_owned_cache_lets_invalidation_propagate(self) -> None:
        """build_default_completer's cache parameter lets callers
        retain a reference to the cache for ``:rescan``-shaped
        invalidation.  The default-completer wrapping must thread it
        through to the underlying DeviceCompleter so a clear() on the
        caller's reference forces a re-fetch on the next Tab.
        """
        pytest.importorskip("prompt_toolkit")
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document

        # First round-trip: device says ['alpha'].  Second round-trip:
        # device says ['beta'].  An interposed clear() should reach
        # the second snapshot on the next Tab.
        port = FakeSerialPort(read_chunks=[
            # Round 1.
            b"raw REPL; CTRL-B to exit\r\n>",
            b"OK['alpha']\n\x04\x04>",
            b"\r\n>>> ",
            # Round 2 (after cache.clear()).
            b"raw REPL; CTRL-B to exit\r\n>",
            b"OK['beta']\n\x04\x04>",
            b"\r\n>>> ",
        ])
        cache = CompletionCache()
        completer = build_default_completer(
            port=port, time=FakeTime(), cache=cache,
        )

        document = Document("a", cursor_position=1)
        first = [
            completion.text
            for completion in completer.get_completions(  # type: ignore[attr-defined]
                document, CompleteEvent(),
            )
        ]
        assert "alpha" in first

        cache.clear()

        document = Document("b", cursor_position=1)
        second = [
            completion.text
            for completion in completer.get_completions(  # type: ignore[attr-defined]
                document, CompleteEvent(),
            )
        ]
        assert "beta" in second


class TestFetchDeviceNames:
    """Drives the friendly→raw→dir()→friendly round-trip end-to-end."""

    def _scripted_port(
        self,
        names_repr: bytes = b"['foo', 'bar', '_private']",
    ) -> FakeSerialPort:
        return FakeSerialPort(read_chunks=[
            b"\r\n",  # whatever drift was in flight before Ctrl-A
            b"raw REPL; CTRL-B to exit\r\n>",
            b"OK" + names_repr + b"\n\x04\x04>",
            b"\r\nMicroPython v1.28.0\r\n>>> ",
        ])

    def test_happy_path_returns_sorted_public_names(self) -> None:
        port = self._scripted_port()
        names = fetch_device_names(port, time=FakeTime())
        # Sorted, dedup'd, and `_private` filtered out (matches
        # KeywordCompleter's "no dunders / no leading-underscore"
        # convention).
        assert names == ["bar", "foo"]

    def test_sends_the_expected_byte_sequence(self) -> None:
        port = self._scripted_port()
        fetch_device_names(port, time=FakeTime())
        # Must have written: Ctrl-C Ctrl-C Ctrl-A, the dir() command
        # (with trailing Ctrl-D), then Ctrl-B.  We stitch the writes
        # together to compare, since the fetcher may flush in any
        # number of chunks.
        joined = b"".join(port.writes)
        assert joined.startswith(b"\x03\x03\x01")
        assert b"print(repr(dir()))" in joined
        assert b"\x04" in joined
        assert joined.endswith(b"\x02")

    def test_expression_parameter_substitutes_into_dir(self) -> None:
        port = FakeSerialPort(read_chunks=[
            b"raw REPL; CTRL-B to exit\r\n>",
            b"OK['radio', 'connect']\n\x04\x04>",
            b"\r\n>>> ",
        ])
        names = fetch_device_names(
            port, expression="wifi", time=FakeTime(),
        )
        assert names == ["connect", "radio"]
        joined = b"".join(port.writes)
        assert b"print(repr(dir(wifi)))" in joined

    def test_timeout_returns_none(self) -> None:
        # No raw-REPL banner ever arrives; the fetcher times out and
        # returns None.  Best-effort recovery sends Ctrl-B.
        port = FakeSerialPort(read_chunks=[])
        names = fetch_device_names(
            port, time=FakeTime(), timeout=0.01,
        )
        assert names is None

    def test_garbage_repr_returns_none(self) -> None:
        port = FakeSerialPort(read_chunks=[
            b"raw REPL; CTRL-B to exit\r\n>",
            b"OKnot a list literal\n\x04\x04>",
            b"\r\n>>> ",
        ])
        names = fetch_device_names(port, time=FakeTime())
        assert names is None

    def test_empty_list_returns_empty(self) -> None:
        port = FakeSerialPort(read_chunks=[
            b"raw REPL; CTRL-B to exit\r\n>",
            b"OK[]\n\x04\x04>",
            b"\r\n>>> ",
        ])
        names = fetch_device_names(port, time=FakeTime())
        assert names == []


class TestParseDirResponse:
    """The repr-parser is robust against partial / malformed frames."""

    def test_well_formed_response(self) -> None:
        assert _parse_dir_response(
            b"OK['foo', 'bar']\n\x04\x04>",
        ) == ["bar", "foo"]

    def test_filters_dunders_and_private(self) -> None:
        assert _parse_dir_response(
            b"OK['__name__', '_private', 'foo', '__init__']\n\x04\x04>",
        ) == ["foo"]

    def test_no_ok_marker_returns_none(self) -> None:
        assert _parse_dir_response(b"garbage\x04>") is None

    def test_no_eot_marker_returns_none(self) -> None:
        assert _parse_dir_response(b"OK['foo']") is None

    def test_non_list_repr_returns_none(self) -> None:
        # `dir()` always returns a list, but a buggy response that
        # came back as a tuple repr should not corrupt the cache.
        assert _parse_dir_response(b"OK('foo', 'bar')\n\x04\x04>") is None

    def test_unparseable_repr_returns_none(self) -> None:
        # A repr containing a non-literal Python type — e.g. an
        # expression literal_eval refuses — falls back to None.
        assert _parse_dir_response(b"OK[<built-in>]\n\x04\x04>") is None
