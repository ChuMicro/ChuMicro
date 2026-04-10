"""Test helpers for libraries that depend on chumicro-timing.

Provides deterministic fakes that replace the real tick functions,
allowing host-side tests to control time without wall-clock waits.

Ships with the library per Decision 0010 so downstream consumers
import ready-made fakes rather than inventing ad-hoc mocks.

Example:
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

# Define tick constants directly rather than importing from ticks.py.
# On CircuitPython, const()-decorated private names in ticks.py may be
# compiled away and not importable.  These are mathematical constants
# (the 2**29 tick period) that cannot drift between modules.
TICKS_PERIOD = 1 << 29
TICKS_MAX = TICKS_PERIOD - 1
TICKS_HALFPERIOD = TICKS_PERIOD // 2


class FakeTicks:
    """Deterministic tick source for host-side tests.

    Replaces the real ``ticks_ms`` / ``ticks_diff`` / ``ticks_add``
    contract with values that only move when ``advance()`` is called
    explicitly.  Models the 2²⁹ ms wraparound period so downstream
    code is tested against the real tick semantics.
    """

    __slots__ = ("_current_ms",)

    def __init__(self, start_ms: int = 0) -> None:
        """Create a fake tick source starting at *start_ms*.

        Args:
            start_ms: Initial tick value (masked to the tick period).
        """
        self._current_ms = start_ms

    @property
    def current_ms(self) -> int:
        """Return the raw internal counter (unmasked).

        Prefer ``ticks_ms()`` for values that match the production
        contract.  This property exists for backward compatibility
        and for tests that need to inspect the raw counter.
        """
        return self._current_ms

    @current_ms.setter
    def current_ms(self, value: int) -> None:
        """Set the raw internal counter."""
        self._current_ms = value

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
