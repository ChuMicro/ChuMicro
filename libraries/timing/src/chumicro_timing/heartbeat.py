"""Periodic heartbeat driven by cross-runtime tick helpers."""


class Heartbeat:
    """Track whether a periodic heartbeat is due based on monotonic ticks.

    Pass a shared ``now_ms`` timestamp to ``poll()`` and ``is_due()`` on
    each loop iteration.  The timestamp should be captured once per loop
    and shared across all components to avoid time drift.

    By default, uses the module-level ``ticks_diff`` helper for
    wraparound-safe comparison.  Pass a *ticks* object with ``ticks_ms``
    and ``ticks_diff`` methods to override (e.g. for tests).
    """

    def __init__(self, period_ms, ticks=None):
        """Create a heartbeat that becomes due once every *period_ms* milliseconds.

        Args:
            period_ms: Interval between beats.
            ticks: Optional tick source (must have ``ticks_ms`` and
                ``ticks_diff`` methods).  Defaults to the real clock.
                Constructor injection per Decision 0010; pass
                ``FakeTicks`` from ``chumicro_timing.testing`` in tests.
        """
        if period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")

        self._period_ms = period_ms
        if ticks is not None:
            self._ticks_diff = ticks.ticks_diff
            self._last_beat_ms = ticks.ticks_ms()
        else:
            from .ticks import ticks_diff, ticks_ms

            self._ticks_diff = ticks_diff
            self._last_beat_ms = ticks_ms()

    @property
    def period_ms(self):
        """Return the configured heartbeat period in milliseconds."""
        return self._period_ms

    def reset(self, now_ms):
        """Reset the heartbeat schedule to start counting from *now_ms*."""
        self._last_beat_ms = now_ms

    def is_due(self, now_ms):
        """Return whether the heartbeat period has elapsed since the last beat."""
        return self._ticks_diff(now_ms, self._last_beat_ms) >= self._period_ms

    def poll(self, now_ms):
        """Return ``True`` once per elapsed period and advance the heartbeat state."""
        if not self.is_due(now_ms):
            return False

        self._last_beat_ms = now_ms
        return True
