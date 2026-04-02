"""Periodic heartbeat driven by cross-runtime tick helpers."""


class Heartbeat:
    """Track whether a periodic heartbeat is due based on monotonic ticks.

    By default uses the module-level ``ticks_ms`` and ``ticks_diff`` helpers.
    Pass a *ticks* object with the same two methods to override (e.g. for tests).
    """

    def __init__(self, period_ms, ticks=None):
        """Create a heartbeat that becomes due once every *period_ms* milliseconds."""
        if period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")

        self._period_ms = period_ms
        if ticks is not None:
            self._ticks_ms = ticks.ticks_ms
            self._ticks_diff = ticks.ticks_diff
        else:
            from .ticks import ticks_diff, ticks_ms

            self._ticks_ms = ticks_ms
            self._ticks_diff = ticks_diff
        self._last_beat_ms = self._ticks_ms()

    @property
    def period_ms(self):
        """Return the configured heartbeat period in milliseconds."""
        return self._period_ms

    def reset(self):
        """Reset the heartbeat schedule to start again from the current tick."""
        self._last_beat_ms = self._ticks_ms()

    def is_due(self):
        """Return whether the heartbeat period has elapsed since the last beat."""
        return self._ticks_diff(self._ticks_ms(), self._last_beat_ms) >= self._period_ms

    def poll(self):
        """Return ``True`` once per elapsed period and advance the heartbeat state."""
        if not self.is_due():
            return False

        self._last_beat_ms = self._ticks_ms()
        return True

