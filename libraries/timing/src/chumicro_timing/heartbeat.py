"""Fires at a fixed ``period_ms`` cadence against a wrap-safe ticks source."""

from chumicro_timing import ticks as _DEFAULT_TICKS


class Heartbeat:
    """Reports when ``period_ms`` has elapsed since the last fire, using wrap-safe tick math."""

    def __init__(self, period_ms: int, ticks: object | None = None) -> None:
        """Builds a heartbeat with ``period_ms`` interval; first fire lands one period later.

        Args:
            period_ms: Interval between fires; must be greater than zero.
            ticks: Object with ``ticks_ms`` and ``ticks_diff`` methods.
                Defaults to ``chumicro_timing.ticks``.

        Raises:
            ValueError: When ``period_ms`` is not greater than zero.
        """
        if period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")

        self.period_ms = period_ms
        self._ticks = ticks if ticks is not None else _DEFAULT_TICKS
        self._last_beat_ms = self._ticks.ticks_ms()

    def reset(self, now_ms: int) -> None:
        """Restarts the period from ``now_ms`` so the next fire lands one ``period_ms`` later."""
        self._last_beat_ms = now_ms

    def poll(self, now_ms: int) -> bool:
        """Returns ``True`` when ``period_ms`` has passed since the last fire, re-anchoring to ``now_ms``."""
        if self._ticks.ticks_diff(now_ms, self._last_beat_ms) < self.period_ms:
            return False
        self._last_beat_ms = now_ms
        return True
