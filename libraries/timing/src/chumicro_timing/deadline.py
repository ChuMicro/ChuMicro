"""``Deadline`` and ``Rate``: a one-shot timeout and a repeating timer for a loop that never sleeps.

Each method takes the current tick as ``now_ms``, so one ``ticks_ms()`` reading per pass of
the loop drives every timer.
"""

from chumicro_timing.ticks import TICKS_HALFPERIOD, ticks_add, ticks_diff


class Deadline:
    """A one-shot timer that expires ``period_ms`` milliseconds after it is built.

    Build it when a wait starts, then ask ``expired(now_ms)`` on each pass of the loop.  Once
    expired it stays expired until ``reset`` starts it over.  A sensor read that gives up
    after 2 seconds is the typical use.

    Args:
        period_ms: Milliseconds until the deadline expires.
        now_ms: The current tick, from ``ticks_ms()``.

    Attributes:
        period_ms: The length of the wait in milliseconds, which ``reset`` reuses.

    Raises:
        OverflowError: ``period_ms`` is 2**28 ms (about 3.1 days) or longer.
    """

    def __init__(self, period_ms: int, now_ms: int) -> None:
        self.period_ms = period_ms
        self._due_ms = ticks_add(now_ms, period_ms)

    def expired(self, now_ms: int) -> bool:
        """Return True once ``now_ms``, the current tick, has reached the deadline."""
        return ticks_diff(now_ms, self._due_ms) >= 0

    def remaining(self, now_ms: int) -> int:
        """Return the milliseconds left before the deadline at ``now_ms``, or 0 once it has passed."""
        left = ticks_diff(self._due_ms, now_ms)
        return left if left > 0 else 0

    def reset(self, now_ms: int) -> None:
        """Start the deadline over, so it expires ``period_ms`` after ``now_ms``."""
        self._due_ms = ticks_add(now_ms, self.period_ms)


class Rate:
    """A repeating timer that comes due once every ``period_ms`` milliseconds.

    Ask ``due(now_ms)`` on each pass of the loop and do the work when it returns True.  The
    schedule counts from when the timer was built, so a late pass leaves the next one on
    time: a 500 ms rate answered 30 ms late comes due again 470 ms later.  After a stall
    longer than one period, ``due`` returns True once and skips the periods it missed.

    Args:
        period_ms: Milliseconds between fires.
        now_ms: The current tick, from ``ticks_ms()``.  The first fire lands ``period_ms``
            after it.

    Attributes:
        period_ms: The interval in milliseconds.

    Raises:
        ValueError: ``period_ms`` is 0 or less, or 2**28 ms (about 3.1 days) or more.
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
        """Return True when a period has come due at ``now_ms``, and schedule the next one.

        A True answer moves the schedule on, so a second call at the same tick returns False.
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
        """Restart the schedule, so the next fire lands ``period_ms`` after ``now_ms``."""
        self._next_due_ms = ticks_add(now_ms, self.period_ms)
