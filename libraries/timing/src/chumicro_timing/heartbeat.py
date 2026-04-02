"""Heartbeat logic driven by an injected tick source."""

from .ticks import _SystemTicks


class Heartbeat:
    """Track whether a periodic heartbeat is due based on monotonic ticks."""

    def __init__(self, period_ms, ticks=None):
        """Create a heartbeat that becomes due once every `period_ms` milliseconds."""
        if period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")

        self._period_ms = period_ms
        self._ticks = ticks or _SystemTicks()
        self._last_beat_ms = self._ticks.ticks_ms()

    @property
    def period_ms(self):
        """Return the configured heartbeat period in milliseconds."""
        return self._period_ms

    def reset(self):
        """Reset the heartbeat schedule to start again from the current tick."""
        self._last_beat_ms = self._ticks.ticks_ms()

    def is_due(self):
        """Return whether the heartbeat period has elapsed since the last beat."""
        current_ticks = self._ticks.ticks_ms()
        return self._ticks.ticks_diff(current_ticks, self._last_beat_ms) >= self._period_ms

    def poll(self):
        """Return `True` once per elapsed period and advance the heartbeat state."""
        if not self.is_due():
            return False

        self._last_beat_ms = self._ticks.ticks_ms()
        return True

