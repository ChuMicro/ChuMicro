"""Periodic heartbeat driven by cross-runtime tick helpers."""


class Heartbeat:
    """Track whether a periodic heartbeat is due based on monotonic ticks.

    By default uses the module-level ``ticks_ms`` and ``ticks_diff`` helpers.
    Pass a *ticks* object with the same two methods to override (e.g. for tests).

    Supports both the simple ``poll()`` API and the serviceable pattern::

        # Simple usage
        if heartbeat.poll():
            do_work()

        # Serviceable pattern
        heartbeat.service(event_sink)
    """

    EVENT_TICK = "heartbeat.tick"
    """Default event type emitted by ``service()`` when a beat is due."""

    def __init__(self, period_ms, ticks=None, event_type=None):
        """Create a heartbeat that becomes due once every *period_ms* milliseconds.

        Args:
            period_ms: Interval between beats.
            ticks: Optional tick source (must have ``ticks_ms`` and
                ``ticks_diff`` methods).  Defaults to the real clock.
            event_type: Event type string emitted by ``service()``.
                Defaults to ``EVENT_TICK``.  Override this when multiple
                heartbeats share a sink so handlers can distinguish them.
        """
        if period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")

        self._period_ms = period_ms
        self._event_type = event_type if event_type is not None else self.EVENT_TICK
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

    @property
    def event_type(self):
        """Return the event type string emitted by ``service()``."""
        return self._event_type

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

    def service(self, event_sink):
        """Service one tick: emit the configured event type into *event_sink* if due.

        This is the serviceable-pattern equivalent of ``poll()``.  Use it
        with ``ServiceRunner`` from ``chumicro_serviceable`` for a standard
        dispatch loop.
        """
        if self.poll():
            event_sink.emit(self, self._event_type)

