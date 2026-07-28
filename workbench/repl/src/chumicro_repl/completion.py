"""Tab-completion for the line-mode REPL.

Provides a :class:`Completer` protocol, two implementations (a
static keyword/builtins catalog and a device-backed fetcher), a
:class:`CombinedCompleter` that layers them, and a prompt_toolkit
adapter.

The device-backed source drives a friendly-REPL to raw-REPL to
``dir()`` round-trip per Tab and caches the result, so successive
Tabs are served from memory.  The fetcher
runs synchronously inside the prompt_toolkit callback because the
line-mode loop is parked in ``session.prompt(...)`` while the user
is typing, so nothing else is touching the port.
"""

from __future__ import annotations

import ast
import builtins
import keyword
import re
import time as _time_module
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Protocol, cast

from ._serial import (
    CTRL_A,
    CTRL_B,
    CTRL_C,
    CTRL_D,
    RAW_REPL_EOT,
    RAW_REPL_PROMPT,
    SerialPort,
    TimeSource,
    read_chunk,
)

if TYPE_CHECKING:  # pragma: no cover -type-only
    from prompt_toolkit.completion import CompleteEvent, Completion
    from prompt_toolkit.document import Document


#: Callable signature for the fetcher that backs a :class:`DeviceCompleter`.
#: Returns the device's top-level ``dir()`` names, or ``None`` on a soft
#: failure (timeout / parse error).  Callers retry on the next Tab.
NamespaceFetcher = Callable[[], Iterable[str] | None]


#: Identifier-ish character class for the trailing token of a
#: partial-word completion.
_IDENTIFIER_TAIL = re.compile(r"[A-Za-z_][A-Za-z_0-9]*$")


def _completable_tail(text_before_cursor: str) -> str:
    """Return the trailing identifier-shape from *text_before_cursor*.

    Examples: ``"x = pri"`` yields ``"pri"``; ``"foo()"`` yields
    ``""``; ``"x.y"`` yields ``"y"`` (the symbol fragment only, not
    the namespace it would belong to).
    """
    match = _IDENTIFIER_TAIL.search(text_before_cursor)
    return match.group(0) if match else ""


# ---------------------------------------------------------------------------
# Completer protocol
# ---------------------------------------------------------------------------


class Completer(Protocol):
    """Structural interface for a completion source.

    Returns plain ``str`` candidates rather than
    ``prompt_toolkit.Completion`` objects so implementations stay
    testable without a prompt_toolkit dependency.
    """

    def candidates(self, prefix: str) -> Iterable[str]:
        """Return completion strings whose start matches *prefix*."""
        ...


# ---------------------------------------------------------------------------
# Static keyword + builtins completer
# ---------------------------------------------------------------------------


def _python_keywords() -> list[str]:
    """Return the language keywords that make sense at the prompt.

    ``keyword.kwlist`` carries language reserved words; ``softkwlist``
    covers ``match`` / ``case`` / ``type``.  Combined + sorted gives
    a stable list.
    """
    return sorted(set(keyword.kwlist) | set(keyword.softkwlist))


def _public_builtin_names() -> list[str]:
    """Return public names from `builtins` (anything not starting with `_`).

    Filters dunders (``__import__`` etc.) so Tab only surfaces the
    public builtins (``print``, ``range``, ``len``, ``enumerate``, ...).
    """
    return sorted(
        name for name in dir(builtins) if not name.startswith("_")
    )


#: Combined static catalog of keywords + public builtins, sorted
#: alphabetically.  Computed once at module load.
STATIC_CATALOG: tuple[str, ...] = tuple(
    sorted(set(_python_keywords()) | set(_public_builtin_names())),
)


class KeywordCompleter:
    """Static catalog completer: Python keywords + public builtins.

    Zero device interaction; works on every Tab regardless of board
    state.  Composes with :class:`DeviceCompleter` via
    :class:`CombinedCompleter` to add session-specific names.
    """

    __slots__ = ("_catalog",)

    def __init__(self, catalog: Iterable[str] | None = None) -> None:
        self._catalog = tuple(catalog) if catalog is not None else STATIC_CATALOG

    def candidates(self, prefix: str) -> Iterable[str]:
        if not prefix:
            return iter(self._catalog)
        # Linear scan; the catalog is small enough that a trie is not
        # worth the overhead.
        return (entry for entry in self._catalog if entry.startswith(prefix))


# ---------------------------------------------------------------------------
# Cache + device-backed completer
# ---------------------------------------------------------------------------


class CompletionCache:
    """In-memory cache of the device's top-level ``dir()`` names.

    Holds one sorted, de-duplicated tuple until :meth:`clear` drops it
    (called on every device reset).
    """

    def __init__(self) -> None:
        self._names: tuple[str, ...] | None = None

    def get(self) -> tuple[str, ...] | None:
        return self._names

    def put(self, names: Iterable[str]) -> None:
        self._names = tuple(sorted(set(names)))

    def clear(self) -> None:
        """Drop the cached names; call on device reset."""
        self._names = None


class DeviceCompleter:
    """Cache-fronted completer driven by a :class:`NamespaceFetcher`.

    The first query calls the fetcher for the device's ``dir()`` names
    and stores them; subsequent queries for any prefix hit the cache.
    A ``None`` from the fetcher is a soft failure (timeout, parse error)
    and is not cached, so the next Tab retries.
    """

    def __init__(
        self,
        *,
        fetcher: NamespaceFetcher | None = None,
        cache: CompletionCache | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._cache = cache if cache is not None else CompletionCache()

    @property
    def cache(self) -> CompletionCache:
        """Expose the underlying cache for explicit invalidation."""
        return self._cache

    def candidates(self, prefix: str) -> Iterable[str]:
        cached = self._cache.get()
        if cached is None and self._fetcher is not None:
            fetched = self._fetcher()
            if fetched is not None:
                self._cache.put(fetched)
                cached = self._cache.get()
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

    Yields each candidate once across all sources, sorted
    alphabetically.  A name that appears in more than one source is
    emitted only once.
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

    Callers wiring their own prompt_toolkit session instantiate this
    directly with a chosen completion source.
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
# Device-side fetcher: the friendly→raw→dir()→friendly round-trip
# ---------------------------------------------------------------------------


#: Wall-clock budget for one :func:`fetch_device_names` round-trip.
#: A healthy device responds in tens of milliseconds; the 2 s ceiling
#: leaves room for a board that is mid-busy without hanging the
#: prompt.
_FETCH_TIMEOUT_SECONDS: float = 2.0

#: Inner poll interval for the fetcher's read loop.  Short enough to
#: keep latency in the tens of ms; long enough to avoid pegging the
#: CPU when the device is briefly silent.
_FETCH_POLL_INTERVAL: float = 0.005

#: Friendly-REPL prompt the device emits after ``Ctrl-B``.  The
#: fetcher reads through this so the banner reprint preceding it is
#: consumed cleanly.
_FRIENDLY_PROMPT: bytes = b">>> "


def _read_until_marker(
    port: SerialPort,
    marker: bytes,
    *,
    deadline: float,
    time: TimeSource,
) -> bytes:
    """Drain *port* until *marker* appears in the accumulated bytes.

    Returns the full accumulated buffer (the marker included).
    Raises :class:`TimeoutError` if *deadline* elapses first.
    """
    accumulated = bytearray()
    while True:
        if marker in accumulated:
            return bytes(accumulated)
        chunk = read_chunk(port)
        if chunk:
            accumulated.extend(chunk)
            continue
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"timed out waiting for {marker!r}; got {bytes(accumulated)!r}"
            )
        time.sleep(_FETCH_POLL_INTERVAL)


def fetch_device_names(
    port: SerialPort,
    *,
    time: TimeSource | None = None,
    timeout: float = _FETCH_TIMEOUT_SECONDS,
) -> list[str] | None:
    """Query the device for its top-level ``dir()`` and return the names.

    Drives one friendly-REPL → raw-REPL → ``print(repr(dir()))`` →
    friendly-REPL round-trip.  Reads through the friendly-banner
    reprint so its bytes do not surface into the next drain.

    Args:
        port: Open :class:`SerialPort` already in friendly REPL.  The
            fetcher leaves the device back in friendly REPL on every
            return path (success, parse failure, timeout).
        time: Injectable :class:`TimeSource` for tests.  Defaults to
            the stdlib ``time`` module.
        timeout: Per-round-trip wall-clock budget.  Default 2 s.

    Returns:
        Sorted list of names, or ``None`` if the round-trip failed
        (timeout, parse error, port error).  ``DeviceCompleter`` treats
        ``None`` as "retry on next Tab"; an empty list means
        "successfully queried, nothing to suggest".
    """
    active_time = time if time is not None else cast(TimeSource, _time_module)
    deadline = active_time.monotonic() + timeout
    source = "print(repr(dir()))\r\n"
    try:
        # friendly → raw
        port.reset_input_buffer()
        port.write(CTRL_C + CTRL_C + CTRL_A)
        _read_until_marker(port, RAW_REPL_PROMPT, deadline=deadline, time=active_time)
        # run dir()
        port.write(source.encode("utf-8") + CTRL_D)
        response = _read_until_marker(
            port, RAW_REPL_EOT + b">", deadline=deadline, time=active_time,
        )
    except (OSError, TimeoutError):
        # Best-effort restore to friendly REPL before bailing.
        try:
            port.write(CTRL_B)
            _read_until_marker(
                port, _FRIENDLY_PROMPT, deadline=deadline, time=active_time,
            )
        except (OSError, TimeoutError):  # pragma: no cover -replug-then-replug
            pass
        return None
    # raw → friendly (consume the banner reprint cleanly)
    try:
        port.write(CTRL_B)
        _read_until_marker(
            port, _FRIENDLY_PROMPT, deadline=deadline, time=active_time,
        )
    except (OSError, TimeoutError):
        return None
    return _parse_dir_response(response)


def _parse_dir_response(response: bytes) -> list[str] | None:
    """Extract the ``dir()`` list from a raw-REPL ``OK<stdout>\\x04<stderr>\\x04>``.

    Returns ``None`` on any parse failure, which the caller treats as
    "retry on next Tab" rather than poisoning the cache.
    """
    if b"OK" not in response:
        return None
    body = response.split(b"OK", 1)[1]
    if RAW_REPL_EOT not in body:
        return None
    stdout, _, _rest = body.partition(RAW_REPL_EOT)
    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(parsed, list):
        return None
    names: list[str] = []
    for entry in parsed:
        if isinstance(entry, str) and not entry.startswith("_"):
            names.append(entry)
    return sorted(set(names))


# ---------------------------------------------------------------------------
# Default completer factory
# ---------------------------------------------------------------------------


def build_default_completer(
    *,
    port: SerialPort | None = None,
    time: TimeSource | None = None,
    cache: CompletionCache | None = None,
) -> object:
    """Return a `prompt_toolkit.completion.Completer` for line mode.

    Composes :class:`KeywordCompleter` (always on) with a
    :class:`DeviceCompleter` wired to :func:`fetch_device_names` when
    *port* is given.  When *port* is ``None``, only the static
    keyword/builtins catalog is offered, which is useful for tests and for
    calling code that hasn't opened a port yet.

    Args:
        port: Open :class:`SerialPort` in friendly REPL.  When given,
            Tab-presses query ``dir()`` on the device and cache the
            result.
        time: Injectable :class:`TimeSource` for tests.
        cache: Pre-constructed :class:`CompletionCache` the caller
            can retain for ``:rescan``-style invalidation.  Defaults
            to an internally-managed cache.

    Returns:
        A :class:`PromptToolkitCompleter` ready to plug into a
        ``prompt_toolkit.PromptSession``.
    """
    keyword_source = KeywordCompleter()
    if port is None:
        return PromptToolkitCompleter(CombinedCompleter([keyword_source]))
    device_source = DeviceCompleter(
        fetcher=lambda: fetch_device_names(port, time=time),
        cache=cache,
    )
    return PromptToolkitCompleter(
        CombinedCompleter([keyword_source, device_source]),
    )
