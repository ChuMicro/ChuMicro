"""Board-to-host sync via stdout markers.

A board prints ``<NAME> key=value key=value ...`` lines on its stdout to
signal checkpoints back to the host — e.g. ``SERVER_READY ip=192.168.1.50
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
"""

from __future__ import annotations

import queue
import re
import time
from dataclasses import dataclass, field

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
      :data:`_RESERVED_MARKER_NAMES` — they belong to
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
    the transport's ``execute``) calls :meth:`push` as markers arrive.
    A host fixture calls :meth:`wait_for` to block until a marker with
    a given name lands.

    Non-matching markers that arrive while a :meth:`wait_for` is
    pending are dropped — a fixture wants its specific sync signal,
    not the cumulative log.  A future expansion that registers
    multiple concurrent consumers would need to revisit that drop
    semantic, but for the single-fixture-per-test shape this submodule
    targets today, dropping is what keeps the API predictable.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[Marker] = queue.Queue()

    def push(self, marker: Marker) -> None:
        """Add *marker* to the queue. Called from the stdout-dispatcher thread."""
        self._queue.put(marker)

    def wait_for(self, name: str, *, timeout_s: float) -> Marker:
        """Block until a marker named *name* arrives, or raise on timeout.

        Args:
            name: The marker name to wait for (uppercase identifier).
            timeout_s: Seconds to wait before giving up.

        Returns:
            The matching :class:`Marker` (popped off the queue).

        Raises:
            MarkerTimeoutError: No matching marker arrived within
                *timeout_s* seconds.  The message names the awaited
                marker so a failing test points at the missing
                checkpoint instead of surfacing a generic queue-empty.
        """
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MarkerTimeoutError(
                    f"Timed out after {timeout_s:.3f}s waiting for "
                    f"marker {name!r}",
                )
            try:
                marker = self._queue.get(timeout=remaining)
            except queue.Empty as empty:
                raise MarkerTimeoutError(
                    f"Timed out after {timeout_s:.3f}s waiting for "
                    f"marker {name!r}",
                ) from empty
            if marker.name == name:
                return marker
