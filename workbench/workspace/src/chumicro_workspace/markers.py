"""Board-to-host sync via stdout markers.

A board prints ``<NAME> key=value key=value ...`` lines on its stdout to
signal checkpoints back to the host, e.g. ``SERVER_READY ip=192.168.1.50
port=8765`` once an HTTP server starts accepting connections.  The
streaming transport's ``on_line`` hook feeds each captured stdout line
through :func:`parse_marker`; matches land on a :class:`MarkerQueue`
that host fixtures block on via :meth:`MarkerQueue.wait_for`.

Names reserved by :mod:`result_parser` (``PASS`` / ``FAIL`` / ``SKIP`` /
``SUMMARY`` / ``HEAP``) never parse as markers.  ``SUMMARY total=N
failed=N time=N.Ns`` in particular is shaped exactly like a marker line
and would otherwise be picked up here as well.

Marker syntax:

* First word is an uppercase identifier matching ``[A-Z][A-Z0-9_]*``.
* Each remaining whitespace-separated token is ``key=value`` where
  ``key`` is an ASCII identifier and ``value`` contains no whitespace
  and no ``=``.
* A marker name with no values (just ``READY`` on a line) is valid.
* Anything else parses as :data:`None`, including free-form board prose,
  traceback frames, and pytest result-parser lines.

A line that *tried* to be a marker but failed (uppercase first word
plus at least one well-formed ``key=value`` token, but another token
malformed, typically a value containing whitespace) still parses as
:data:`None`, but :meth:`MarkerQueue.offer_line` records it as a
near-miss so a later :meth:`MarkerQueue.wait_for` timeout names the
mangled line instead of presenting an empty queue.
"""

from __future__ import annotations

import queue
import re
import time
from dataclasses import dataclass, field

# Bounds for the diagnostic state a queue accumulates between waits: a
# long bake streaming unrelated markers must not grow host memory
# without limit, so both retention buffers drop-oldest at their cap.
_DEFERRED_MARKER_CAP = 256
_MALFORMED_LINE_CAP = 8

_MARKER_NAME_PATTERN = re.compile(r"^([A-Z][A-Z0-9_]*)(?:\s+(.*))?$")
_KEY_VALUE_PATTERN = re.compile(r"^([a-z_][a-z0-9_]*)=([^=\s]+)$")
_RESERVED_MARKER_NAMES = frozenset(
    {"PASS", "FAIL", "SKIP", "SUMMARY", "HEAP"},
)


@dataclass(frozen=True)
class Marker:
    """A single host-side sync signal parsed off a board's stdout line.

    ``name`` is the uppercase identifier (``SERVER_READY``); ``values``
    carries the line's ``key=value`` pairs as a plain dict.  Frozen so
    a fixture can hand a marker back to a test without worrying about
    a downstream caller mutating the name field.
    """

    name: str
    values: dict[str, str] = field(default_factory=dict)


def parse_marker(line: str) -> Marker | None:
    """Parse one captured stdout line into a :class:`Marker` or return None.

    Returns :data:`None` for any line that is not a well-formed marker,
    including:

    * Lines whose first word is in
      :data:`_RESERVED_MARKER_NAMES`, which belong to
      :mod:`result_parser`.
    * Lines whose first word is not an uppercase identifier (leading
      whitespace, lowercase, digit-led, punctuation).
    * Lines whose first word IS uppercase but whose remainder is not
      well-formed ``key=value`` tokens (a free-form trailing phrase
      disqualifies the whole line; partial parsing is not the contract).

    A line carrying just the marker name (no values) parses as a
    :class:`Marker` with an empty ``values`` dict.
    """
    if not line:
        return None
    name_match = _MARKER_NAME_PATTERN.match(line)
    if name_match is None:
        return None
    name = name_match.group(1)
    if name in _RESERVED_MARKER_NAMES:
        return None
    remainder = name_match.group(2)
    values: dict[str, str] = {}
    if remainder is not None:
        for token in remainder.split():
            kv_match = _KEY_VALUE_PATTERN.match(token)
            if kv_match is None:
                return None
            values[kv_match.group(1)] = kv_match.group(2)
    return Marker(name=name, values=values)


class MarkerTimeoutError(TimeoutError):
    """Raised when :meth:`MarkerQueue.wait_for` exhausts its timeout."""


class MarkerQueue:
    """Thread-safe FIFO of parsed markers with a blocking ``wait_for`` primitive.

    The stdout-dispatcher (the board's ``on_line`` callback wired into
    the transport's ``execute``) calls :meth:`offer_line` (or
    :meth:`push` with a pre-parsed marker) as lines arrive.  A host
    fixture calls :meth:`wait_for` to block until a marker with a
    given name lands.

    Non-matching markers that arrive while a :meth:`wait_for` is
    pending are retained (up to ``_DEFERRED_MARKER_CAP``, oldest
    dropped past that) so a later ``wait_for`` for their name still
    succeeds, so a driver waiting on markers in the wrong order gets a
    late match instead of a silent loss.  Markers popped this way also
    feed the timeout diagnostics: a ``wait_for`` that times out names
    what *did* arrive.

    ``wait_for`` assumes a single consumer thread (the
    one-fixture-per-test shape this submodule targets); ``offer_line``
    and ``push`` may run on a different producer thread.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[Marker] = queue.Queue()
        self._deferred: list[Marker] = []
        self._malformed: list[str] = []
        self._malformed_total = 0

    def push(self, marker: Marker) -> None:
        """Add *marker* to the queue. Called from the stdout-dispatcher thread."""
        self._queue.put(marker)

    def offer_line(self, line: str) -> Marker | None:
        """Parse one stdout *line*; push and return its marker, else None.

        Lines that are marker near-misses (uppercase first word plus at
        least one well-formed ``key=value`` token, but another token
        malformed, typically a value containing whitespace) are
        recorded so :meth:`wait_for` timeout messages can name them.
        Everything else (board prose, tracebacks, result-parser lines)
        is ignored.
        """
        marker = parse_marker(line)
        if marker is not None:
            self.push(marker)
            return marker
        name_match = _MARKER_NAME_PATTERN.match(line)
        if name_match is None or name_match.group(1) in _RESERVED_MARKER_NAMES:
            return None
        remainder = name_match.group(2)
        if remainder and any(
            _KEY_VALUE_PATTERN.match(token) for token in remainder.split()
        ):
            if len(self._malformed) >= _MALFORMED_LINE_CAP:
                self._malformed.pop(0)
            self._malformed.append(line)
            self._malformed_total += 1
        return None

    def poll(self, name: str) -> Marker | None:
        """Non-blocking :meth:`wait_for`: return a match if one has arrived.

        Scans retained markers first, then drains whatever is currently
        queued (retaining non-matches), and returns :data:`None` when
        no marker named *name* has arrived yet.  For callers that must
        keep doing work while waiting (e.g. a demo driver ticking a
        host-side client between checks), poll in a loop instead of
        blocking in :meth:`wait_for`.
        """
        match = self._pop_deferred(name)
        if match is not None:
            return match
        while True:
            try:
                marker = self._queue.get_nowait()
            except queue.Empty:
                return None
            if marker.name == name:
                return marker
            self._defer(marker)

    def wait_for(self, name: str, *, timeout_s: float) -> Marker:
        """Block until a marker named *name* arrives, or raise on timeout.

        Args:
            name: The marker name to wait for (uppercase identifier).
            timeout_s: Seconds to wait before giving up.

        Returns:
            The matching :class:`Marker`, either retained from an
            earlier wait or popped off the queue.

        Raises:
            MarkerTimeoutError: No matching marker arrived within
                *timeout_s* seconds.  The message names the awaited
                marker, any non-matching markers that did arrive, and
                any marker-shaped lines that failed to parse, so a
                failing test points at the actual mismatch instead of
                surfacing a generic queue-empty.
        """
        match = self._pop_deferred(name)
        if match is not None:
            return match

        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MarkerTimeoutError(self._timeout_message(name, timeout_s))
            try:
                marker = self._queue.get(timeout=remaining)
            except queue.Empty as empty:
                raise MarkerTimeoutError(
                    self._timeout_message(name, timeout_s),
                ) from empty
            if marker.name == name:
                return marker
            self._defer(marker)

    def _pop_deferred(self, name: str) -> Marker | None:
        """Remove and return the oldest retained marker named *name*, if any."""
        for index, pending in enumerate(self._deferred):
            if pending.name == name:
                return self._deferred.pop(index)
        return None

    def _defer(self, marker: Marker) -> None:
        """Retain a non-matching marker for later waits, oldest dropped at cap."""
        if len(self._deferred) >= _DEFERRED_MARKER_CAP:
            self._deferred.pop(0)
        self._deferred.append(marker)

    def _timeout_message(self, name: str, timeout_s: float) -> str:
        """Build a ``wait_for`` timeout message carrying arrival diagnostics."""
        message = f"Timed out after {timeout_s:.3f}s waiting for marker {name!r}"
        if self._deferred:
            seen: list[str] = []
            for pending in self._deferred:
                if pending.name not in seen:
                    seen.append(pending.name)
            shown = ", ".join(seen[:6]) + (", ..." if len(seen) > 6 else "")
            message += f"; markers seen but not matched: {shown}"
        if self._malformed_total:
            message += (
                f"; {self._malformed_total} marker-shaped line(s) failed to "
                f"parse (values must be whitespace-free key=value), latest: "
                f"{self._malformed[-1]!r}"
            )
        return message
