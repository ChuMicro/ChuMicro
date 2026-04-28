"""Tests for tab completion (Phase 7 Slice 1c)."""

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
    build_default_completer,
)


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

    def test_len_and_contains(self) -> None:
        cache = CompletionCache()
        assert len(cache) == 0
        assert "any" not in cache
        cache.put("", ["a"])
        assert len(cache) == 1
        assert "" in cache


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
