"""Test helpers for libraries that depend on chumicro-timing.

Deterministic fakes that replace the real tick functions, letting
host-side tests control time without wall-clock waits.

Example — tick-domain tests:
    ```python
    from chumicro_timing.testing import FakeTicks

    fake = FakeTicks()
    heartbeat = Heartbeat(period_ms=100, ticks=fake)
    fake.advance(100)
    assert heartbeat.poll(fake.ticks_ms()) is True
    ```

``FakeTicks`` models the full tick contract including the 2²⁹ ms
wraparound period.  Values returned by ``ticks_ms()`` are always in
``[0 .. 2**29 - 1]``, and ``ticks_diff`` uses ring arithmetic — so
tests will catch code that accidentally uses plain subtraction instead
of ``ticks_diff``.
"""

#: Test-support: PyPI sdist / wheel only -- bundles and product /
#: app / functional device deploys exclude it; the on-device unit
#: sweep is the one path that stages it.
__chumicro_test_support__ = True

from chumicro_timing.ticks import TICKS_HALFPERIOD, TICKS_MAX, TICKS_PERIOD


class FakeTicks:
    """Deterministic tick source for host-side tests.

    Replaces the real ``ticks_ms`` / ``ticks_diff`` / ``ticks_add``
    contract with values that only move when ``advance()`` is called
    explicitly.  Models the 2²⁹ ms wraparound period so downstream
    code is tested against the real tick semantics.
    """

    def __init__(self, start_ms: int = 0) -> None:
        """Create a fake tick source starting at *start_ms*.

        Args:
            start_ms: Initial tick value (masked to the tick period).
        """
        self._current_ms = start_ms

    def advance(self, amount_ms: int) -> None:
        """Move the clock forward by *amount_ms* milliseconds.

        Args:
            amount_ms: Milliseconds to advance.
        """
        self._current_ms += amount_ms

    def ticks_ms(self) -> int:
        """Return the current fake tick value in ``[0 .. 2**29 - 1]``."""
        return self._current_ms & TICKS_MAX

    def ticks_diff(self, end: int, start: int) -> int:
        """Wraparound-safe signed difference *end* − *start*.

        Uses the same ring arithmetic as the real ``ticks_diff``.

        Args:
            end: Later tick value.
            start: Earlier tick value.

        Returns:
            Signed difference in milliseconds.
        """
        diff = (end - start) & TICKS_MAX
        return ((diff + TICKS_HALFPERIOD) & TICKS_MAX) - TICKS_HALFPERIOD

    def ticks_add(self, ticks_val: int, delta: int) -> int:
        """Wraparound-safe addition of *delta* to a tick value.

        Matches the real ``ticks_add`` behavior, including raising
        ``OverflowError`` for deltas at or beyond the half-period.

        Args:
            ticks_val: Base tick value.
            delta: Milliseconds to add.

        Returns:
            Wrapped tick value in ``[0 .. 2**29 - 1]``.

        Raises:
            OverflowError: If *delta* is outside (-2**28 .. 2**28).
        """
        if not (-TICKS_HALFPERIOD < delta < TICKS_HALFPERIOD):
            raise OverflowError("ticks interval overflow")
        return (ticks_val + delta) % TICKS_PERIOD
