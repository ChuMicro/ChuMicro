"""Fires a recurring boolean signal every ``period_ms`` milliseconds for runner ticks."""

from chumicro_timing import ticks as _DEFAULT_TICKS


class Heartbeat:
    """Fires ``True`` from ``poll`` once each ``period_ms`` window has elapsed."""

    def __init__(self, period_ms: int, ticks: object | None = None) -> None:
        """Seeds ``_last_beat_ms`` from the injected tick source so the first window starts now.

        Args:
            period_ms: Milliseconds between consecutive ``True`` results from ``poll``.
            ticks: Tick source exposing ``ticks_ms`` and ``ticks_diff``; defaults to
                the module-level ``chumicro_timing.ticks``.

        Raises:
            ValueError: When ``period_ms`` is zero or negative.
        """
        if period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")

        self.period_ms = period_ms
        self._ticks = ticks if ticks is not None else _DEFAULT_TICKS
        self._last_beat_ms = self._ticks.ticks_ms()

    def reset(self, now_ms: int) -> None:
        """Re-anchors ``_last_beat_ms`` to ``now_ms`` so the next beat fires one period later."""
        self._last_beat_ms = now_ms

    def poll(self, now_ms: int) -> bool:
        """Returns ``True`` and re-anchors when ``period_ms`` has elapsed since the last beat."""
        if self._ticks.ticks_diff(now_ms, self._last_beat_ms) < self.period_ms:
            return False
        self._last_beat_ms = now_ms
        return True
