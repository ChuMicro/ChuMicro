"""Value objects over the ticks substrate: ``Deadline`` and ``Rate``.

These capture the arm / expire / remaining / reduce / re-phase arithmetic
that consumers otherwise hand-assemble from the free ``ticks_add`` /
``ticks_diff`` functions.  Every method takes a caller-supplied
``now_ms`` — the objects hold no clock and never read one, so a service
threads its runner's ``now_ms`` through and stays testable with a fake
clock.  All arithmetic goes through the library's own wrap-safe
``ticks_add`` / ``ticks_diff``, so ``now + delta`` is never written by a
caller and the 29-bit wrap footgun is unrepresentable.
"""

from chumicro_timing.ticks import TICKS_HALFPERIOD, ticks_add, ticks_diff


class Deadline:
    """A single armed deadline: ``period_ms`` from the ``now_ms`` it was built at.

    Arms at construction via wrap-safe ``ticks_add`` — a caller never
    writes ``now + delta``.  ``expired`` / ``remaining`` read the armed
    due-tick against a supplied ``now_ms``; ``reset`` re-arms the same
    period from a fresh ``now_ms``.  One long-lived ``Deadline`` field
    per timeout is allocation-free in steady state (armed once, polled
    every tick without allocating); do not build one per tick on a hot
    path — the free ``ticks_add`` / ``ticks_diff`` stay the right tool
    there.
    """

    def __init__(self, period_ms: int, now_ms: int) -> None:
        """Arm a deadline ``period_ms`` after ``now_ms``.

        Args:
            period_ms: Milliseconds from ``now_ms`` until the deadline is
                due.  Must stay under ``TICKS_HALFPERIOD``; a larger
                interval raises ``OverflowError`` from ``ticks_add``,
                because a gap past half the ring aliases to the wrong sign.
            now_ms: The current tick the deadline is armed against.
        """
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

    Absorbs the old ``Heartbeat`` fixed-cadence poller and the scheduler's
    phase-preserving anchoring: ``due`` re-phases by
    advancing the *scheduled* tick by whole periods, not by re-anchoring
    to ``now_ms``, so fires stay aligned to the original cadence and never
    drift.  A stall longer than one period skips the missed fires instead
    of bursting to catch up.
    """

    def __init__(self, period_ms: int, now_ms: int) -> None:
        """Build a rate with ``period_ms`` cadence; the first fire lands one period after ``now_ms``.

        Args:
            period_ms: Interval between fires.  Must be greater than zero
                and less than ``TICKS_HALFPERIOD`` (half the tick ring); a
                longer interval can never fire, because ``ticks_diff``
                saturates at half the ring.
            now_ms: The current tick the cadence is anchored against.

        Raises:
            ValueError: When ``period_ms`` is not greater than zero, or is
                at least ``TICKS_HALFPERIOD`` (it could never fire).
        """
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

        Fires at most once per ``period_ms``.  On a fire, advances the
        scheduled tick by however many whole periods ``now_ms`` is behind
        (dropping missed fires) so the cadence stays phase-aligned rather
        than drifting by the polling jitter.
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
