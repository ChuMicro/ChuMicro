"""Runner-shaped flush pacing for pixel displays."""


class ScreenService:
    """Paces a display panel's flush so no single tick blocks on the bus.

    ``show()`` marks the drawn frame ready.  Once per
    ``refresh_interval_ms`` the service starts a flush and advances it
    one bus transfer per tick, so a full-frame transfer that takes tens
    of milliseconds spreads across ticks instead of stalling the loop.
    Register the service with a ``chumicro_runner.Runner``, or call
    ``check(now_ms)`` / ``handle(now_ms)`` from a hand-written loop.

    The panel is duck-typed and must implement::

        flush()  # returns an iterator; each advance performs one
                 # bounded bus transfer (a page, strip, or window)

    A panel whose whole frame fits one transfer performs it on the
    first advance and stops.  A panel the runtime refreshes in the
    background requests that refresh on the first advance and stops.
    A frame with N transfers completes after N ``handle()`` calls.

    ``show()`` during an active flush marks the next frame rather than
    restarting the current one, so a slow panel always finishes the
    frame it started.

    Args:
        panel: Display driver implementing the flush protocol above.
        refresh_interval_ms: Floor between flush starts.  ``0`` starts
            a new flush on the first tick after every ``show()``.
        ticks: Tick source with ``ticks_ms``, ``ticks_diff``, and
            ``ticks_add``.  Defaults to the real clock.
    """

    def __init__(self, panel: object, refresh_interval_ms: int = 50,
                 ticks: object | None = None) -> None:
        self._panel = panel
        self._refresh_interval_ms = refresh_interval_ms
        if ticks is not None:
            self._ticks_diff = ticks.ticks_diff
            self._ticks_add = ticks.ticks_add
            self._next_start_ms = ticks.ticks_ms()
        else:
            from chumicro_timing import ticks_add, ticks_diff, ticks_ms
            self._ticks_diff = ticks_diff
            self._ticks_add = ticks_add
            self._next_start_ms = ticks_ms()
        self._dirty = False
        self._active_flush = None

    def show(self) -> None:
        """Mark the drawn frame ready; the next due tick starts its flush."""
        self._dirty = True

    def check(self, now_ms: int) -> bool:
        """Return True when a flush is in progress or a marked frame is due.

        Args:
            now_ms: Current time in milliseconds.
        """
        if self._active_flush is not None:
            return True
        if not self._dirty:
            return False
        return self._ticks_diff(now_ms, self._next_start_ms) >= 0

    def handle(self, now_ms: int) -> None:
        """Advance the flush by one bus transfer, starting one if none is active.

        A panel error ends the flush and propagates; the frame is
        dropped, and the next ``show()`` schedules a fresh one.

        Args:
            now_ms: Current time in milliseconds.
        """
        flush = self._active_flush
        if flush is None:
            self._dirty = False
            self._next_start_ms = self._ticks_add(now_ms, self._refresh_interval_ms)
            flush = self._panel.flush()
            self._active_flush = flush
        try:
            next(flush)
        except StopIteration:
            self._active_flush = None
        except BaseException:
            self._active_flush = None
            raise

    def next_deadline(self, now_ms: int) -> int | None:
        """Return when the service next needs a tick, or None when idle.

        An active flush resumes immediately; a marked frame waits for
        the interval floor; a clean panel needs nothing.

        Args:
            now_ms: Current time in milliseconds.
        """
        if self._active_flush is not None:
            return now_ms
        if self._dirty:
            return self._next_start_ms
        return None
