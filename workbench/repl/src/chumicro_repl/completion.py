"""Tab-completion for the line-mode REPL — Phase 7 Slice 1c.

The line-mode loop hands a `prompt_toolkit.completion.Completer`
to its `PromptSession`.  Tab on a partial token then yields a
list of completion strings drawn from one or more *sources*:

* :class:`KeywordCompleter` — Python keywords + common builtins.
  Always works, no device round-trip; covers ~80 % of Tab
  presses (loops, `print`, `range`, `import`, etc.).
* :class:`DeviceCompleter` — protocol for device-backed
  completers that query the on-device REPL for ``dir()`` /
  ``dir(<expr>)``.  This module ships the architecture plus an
  in-memory :class:`CompletionCache` keyed by namespace
  expression; the wire protocol that fills the cache is
  follow-on work (the friendly-REPL ↔ raw-REPL switching
  needed to query the device cleanly mid-session is a
  design pass of its own).

A :class:`CombinedCompleter` glues several sources together so
the static + device-driven streams compose without either source
hiding the other.
"""

from __future__ import annotations

import builtins
import keyword
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover — type-only
    from prompt_toolkit.completion import CompleteEvent, Completion
    from prompt_toolkit.document import Document


#: Identifier-ish character class — matches the trailing token
#: prompt_toolkit hands us as the partial word being completed.
_IDENTIFIER_TAIL = re.compile(r"[A-Za-z_][A-Za-z_0-9]*$")


def _completable_tail(text_before_cursor: str) -> str:
    """Return the trailing identifier-shape from *text_before_cursor*.

    ``"x = pri"`` → ``"pri"``.  ``"foo()"`` → ``""``.  ``"x.y"`` →
    ``"y"`` (attribute completion is partial in v1 — we only match
    the symbol fragment, not the `dir(x)` lookup that would feed it).
    """
    match = _IDENTIFIER_TAIL.search(text_before_cursor)
    return match.group(0) if match else ""


# ---------------------------------------------------------------------------
# Completer protocol
# ---------------------------------------------------------------------------


class Completer(Protocol):
    """Structural interface for a completion source.

    Mirrors the fragment of `prompt_toolkit.completion.Completer`
    we depend on.  The :class:`CombinedCompleter` adapter wraps a
    list of these into the prompt_toolkit class proper so the
    line-mode session can plug in any combination.

    Implementations return an iterable of completion strings —
    plain `str`, not `prompt_toolkit.Completion` objects — so
    sources stay testable without a prompt_toolkit dependency.
    """

    def candidates(self, prefix: str) -> Iterable[str]:
        """Return completion strings whose start matches *prefix*."""
        ...


# ---------------------------------------------------------------------------
# Static keyword + builtins completer
# ---------------------------------------------------------------------------


def _python_keywords() -> list[str]:
    """Return the language keywords that make sense at the prompt.

    ``keyword.kwlist`` carries language reserved words; ``soft_kwlist``
    (Python 3.9+) covers ``match`` / ``case`` / ``type``.  Combined
    + sorted gives a stable list.
    """
    soft = list(getattr(keyword, "softkwlist", ()))
    return sorted(set(keyword.kwlist) | set(soft))


def _public_builtin_names() -> list[str]:
    """Return public names from `builtins` (anything not starting with `_`).

    Filters dunders so users don't see `__import__` etc. — the public
    surface of `print` / `range` / `len` / `range` / `enumerate` / etc.
    is what people actually want from Tab.
    """
    return sorted(
        name for name in dir(builtins) if not name.startswith("_")
    )


#: Combined static catalog — keywords first (alphabetical order
#: keeps the listing predictable; prompt_toolkit re-sorts on its
#: own anyway).  Computed once at module load.
STATIC_CATALOG: tuple[str, ...] = tuple(
    sorted(set(_python_keywords()) | set(_public_builtin_names())),
)


class KeywordCompleter:
    """Static catalog completer — Python keywords + public builtins.

    Zero device interaction; works on every Tab regardless of board
    state.  Covers the lion's share of "what's that builtin called
    again" Tab presses.

    Composes with :class:`DeviceCompleter` via :class:`CombinedCompleter`
    when richer completion lands (the device-backed source
    contributes module / attribute names that are session-specific).
    """

    __slots__ = ("_catalog",)

    def __init__(self, catalog: Iterable[str] | None = None) -> None:
        self._catalog = tuple(catalog) if catalog is not None else STATIC_CATALOG

    def candidates(self, prefix: str) -> Iterable[str]:
        if not prefix:
            return iter(self._catalog)
        # Linear scan — the catalog is small (~150 entries) so the
        # constant factor wins over building a trie.
        return (entry for entry in self._catalog if entry.startswith(prefix))


# ---------------------------------------------------------------------------
# Cache + device-backed completer
# ---------------------------------------------------------------------------


class CompletionCache:
    """In-memory cache keyed by namespace expression.

    ``""`` keys the bare namespace (``dir()``); ``"foo"`` keys
    ``dir(foo)``; ``"foo.bar"`` keys ``dir(foo.bar)``.  Unbounded —
    sessions don't accumulate enough namespaces to matter; the
    cache clears on every device reset.
    """

    def __init__(self) -> None:
        self._table: dict[str, tuple[str, ...]] = {}

    def get(self, key: str) -> tuple[str, ...] | None:
        return self._table.get(key)

    def put(self, key: str, names: Iterable[str]) -> None:
        self._table[key] = tuple(sorted(set(names)))

    def clear(self) -> None:
        """Drop every cached entry — call on device reset."""
        self._table.clear()

    def __len__(self) -> int:
        return len(self._table)

    def __contains__(self, key: object) -> bool:
        return key in self._table


class DeviceCompleter:
    """Pluggable completer fronting a :class:`CompletionCache`.

    Calls a user-supplied *fetcher* to populate the cache when a
    namespace key is queried for the first time; subsequent Tabs
    on the same prefix hit the cache.  ``None`` from the fetcher
    means "no result" — the cache stores an empty tuple so we
    don't re-query a namespace we already know is empty (the user's
    typo of an undefined name) until the next reset.

    The fetcher signature:

        ``(expression: str) -> Iterable[str] | None``

    where *expression* is ``""`` for ``dir()`` or ``"foo.bar"`` for
    ``dir(foo.bar)``.  Returning ``None`` signals a hard failure
    (timeout, parse error) — the caller can inspect the returned
    iterable's emptiness vs. ``None`` to decide whether to fall
    back to other sources.
    """

    def __init__(
        self,
        *,
        fetcher: _NamespaceFetcher | None = None,
        cache: CompletionCache | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._cache = cache if cache is not None else CompletionCache()

    @property
    def cache(self) -> CompletionCache:
        """Expose the underlying cache for explicit invalidation."""
        return self._cache

    def candidates(self, prefix: str) -> Iterable[str]:
        # Slice 1c v1: only the bare namespace ("") is queried.
        # Attribute completion (`foo.bar<Tab>` → `dir(foo)`) lands
        # in a follow-on alongside the wire-protocol implementation.
        cached = self._cache.get("")
        if cached is None and self._fetcher is not None:
            fetched = self._fetcher("")
            if fetched is not None:
                self._cache.put("", fetched)
                cached = self._cache.get("")
        if not cached:
            return iter(())
        if not prefix:
            return iter(cached)
        return (name for name in cached if name.startswith(prefix))


# ---------------------------------------------------------------------------
# Combined completer + prompt_toolkit adapter
# ---------------------------------------------------------------------------


class CombinedCompleter:
    """Layer multiple :class:`Completer` sources into one stream.

    Returns deduplicated candidates in source order; ties broken
    alphabetically so the static catalog leads with keywords + builtins
    and any device-driven source contributes session-specific
    names without hiding the well-known ones.
    """

    def __init__(self, sources: Iterable[Completer]) -> None:
        self._sources = list(sources)

    def candidates(self, prefix: str) -> Iterable[str]:
        seen: set[str] = set()
        results: list[str] = []
        for source in self._sources:
            for entry in source.candidates(prefix):
                if entry in seen:
                    continue
                seen.add(entry)
                results.append(entry)
        results.sort()
        return iter(results)


class PromptToolkitCompleter:
    """Adapter wrapping a :class:`Completer` for `prompt_toolkit`.

    Constructed automatically by :func:`build_default_completer`;
    callers wiring their own prompt_toolkit session use this directly.
    """

    def __init__(self, source: Completer) -> None:
        self._source = source

    def get_completions(
        self,
        document: Document,
        _complete_event: CompleteEvent,
    ) -> Iterable[Completion]:
        from prompt_toolkit.completion import Completion  # noqa: PLC0415

        prefix = _completable_tail(document.text_before_cursor)
        for candidate in self._source.candidates(prefix):
            yield Completion(
                text=candidate,
                start_position=-len(prefix),
            )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


#: Type alias for the fetcher callback expected by `DeviceCompleter`.
#: Defined after the class to keep the public surface readable.
_NamespaceFetcher = "Callable[[str], Iterable[str] | None]"


def build_default_completer() -> object:
    """Return a `prompt_toolkit.completion.Completer` for line mode.

    Composes the static :class:`KeywordCompleter` with an
    empty-fetcher :class:`DeviceCompleter`; users who want device-
    backed completion plug a real fetcher into the `DeviceCompleter`
    constructor and re-build the combined completer.
    """
    keyword_source = KeywordCompleter()
    device_source = DeviceCompleter()
    combined = CombinedCompleter([keyword_source, device_source])
    return PromptToolkitCompleter(combined)


# Re-export for type checkers — Callable type used in the fetcher
# alias.  Done last to avoid forward-reference ordering issues.
