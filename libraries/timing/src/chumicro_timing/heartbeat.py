"""Periodic heartbeat driven by cross-runtime tick helpers."""

# Default tick source imported eagerly at module load.  Lazy import
# inside ``Heartbeat.__init__`` would make the first Heartbeat() call
# on MicroPython mount-mode cost ~1 s, because each fresh import
# becomes an mpremote RPC round-trip.  Eager import shifts the cost
# to module-import time, paid once.
from chumicro_timing import ticks as _DEFAULT_TICKS


class Heartbeat:
    """Track whether a periodic heartbeat is due based on monotonic ticks.

    Pass a shared ``now_ms`` timestamp to ``poll()`` on each loop
    iteration.  The timestamp should be captured once per loop and
    shared across all components to avoid time drift.

    Pass a *ticks* object with ``ticks_ms`` and ``ticks_diff`` methods
    to override the real clock (e.g. for tests).
    """

    def __init__(self, period_ms: int, ticks: object | None = None) -> None:
        """Create a heartbeat that becomes due once every *period_ms* milliseconds.

        Args:
            period_ms: Interval between beats.
            ticks: Optional tick source (must have ``ticks_ms`` and
                ``ticks_diff`` methods).  Defaults to the real clock.
                Tests pass ``FakeTicks`` from ``chumicro_timing.testing``.
        """
        if period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")

        self.period_ms = period_ms
        self._ticks = ticks if ticks is not None else _DEFAULT_TICKS
        self._last_beat_ms = self._ticks.ticks_ms()

    def reset(self, now_ms: int) -> None:
        """Reset the heartbeat schedule to start counting from *now_ms*.

        Args:
            now_ms: Current tick value.
        """
        self._last_beat_ms = now_ms

    def poll(self, now_ms: int) -> bool:
        """Return ``True`` once per elapsed period and advance the heartbeat state.

        When ``poll`` is called late (more than one period after the
        previous fire), the heartbeat fires once and anchors to *now_ms*
        — missed intervals are dropped, not caught up.  For drift-free
        periodic work, compute the next deadline manually with
        ``ticks_add(last_deadline, period_ms)``.

        Args:
            now_ms: Current tick value.

        Returns:
            ``True`` if the period elapsed and the heartbeat advanced.
        """
        if self._ticks.ticks_diff(now_ms, self._last_beat_ms) < self.period_ms:
            return False
        self._last_beat_ms = now_ms
        return True
