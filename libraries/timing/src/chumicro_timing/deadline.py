"""Value objects built on the tick functions: ``Deadline`` and ``Rate``.

Both take a caller-supplied ``now_ms`` and hold no clock of their own, so a
service can thread its runner's ``now_ms`` through them and stay testable
with a fake clock.
"""

from chumicro_timing.ticks import TICKS_HALFPERIOD, ticks_add, ticks_diff


class Deadline:
    """A single armed deadline: ``period_ms`` from the ``now_ms`` it was built at.

    ``expired`` and ``remaining`` check the due tick against a supplied
    ``now_ms``, and ``reset`` re-arms the same period.  Keep one long-lived
    ``Deadline`` per timeout rather than building one each tick on a hot
    path, where the free ``ticks_add`` / ``ticks_diff`` fit better.
    """

    def __init__(self, period_ms: int, now_ms: int) -> None:
        self.period_ms = period_ms
        self._due_ms = ticks_add(now_ms, period_ms)

    def expired(self, now_ms: int) -> bool:
        """Return ``True`` once ``now_ms`` has reached or passed the due tick."""
        return ticks_diff(now_ms, self._due_ms) >= 0

    def remaining(self, now_ms: int) -> int:
        """Return milliseconds until due, clamped at 0 once past the due tick."""
        left = ticks_diff(self._due_ms, now_ms)
        return left if left > 0 else 0

    def reset(self, now_ms: int) -> None:
        """Re-arm the same ``period_ms`` from ``now_ms``."""
        self._due_ms = ticks_add(now_ms, self.period_ms)


class Rate:
    """Fires at most once per ``period_ms``, drift-free and phase-aligned.

    ``due`` advances the scheduled tick by whole periods rather than
    re-anchoring to ``now_ms``, so fires stay on the original cadence.  A
    stall longer than one period skips the missed fires instead of bursting
    to catch up.
    """

    def __init__(self, period_ms: int, now_ms: int) -> None:
        if period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")
        if period_ms >= TICKS_HALFPERIOD:
            raise ValueError(
                f"period_ms must be < {TICKS_HALFPERIOD} (half the tick "
                f"ring); a longer interval can never fire because "
                f"ticks_diff saturates at half the ring",
            )
        self.period_ms = period_ms
        self._next_due_ms = ticks_add(now_ms, period_ms)

    def due(self, now_ms: int) -> bool:
        """Return ``True`` once the period has elapsed, re-phasing to the next fire.

        Fires at most once per ``period_ms``; a fire drops any periods missed
        during a stall rather than firing repeatedly to catch up.
        """
        behind = ticks_diff(now_ms, self._next_due_ms)
        if behind < 0:
            return False
        periods_missed = behind // self.period_ms + 1
        self._next_due_ms = ticks_add(
            self._next_due_ms, periods_missed * self.period_ms,
        )
        return True

    def reset(self, now_ms: int) -> None:
        """Re-anchor the cadence so the next fire lands one ``period_ms`` after ``now_ms``."""
        self._next_due_ms = ticks_add(now_ms, self.period_ms)
