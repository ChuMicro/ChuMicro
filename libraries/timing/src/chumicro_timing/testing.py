"""Test helpers for libraries that depend on chumicro-timing.

Two flavors live here:

* :class:`FakeTicks` — deterministic fake tick source that replaces
  the real tick functions so host-side tests control time without
  wall-clock waits.  Models the 2²⁹ ms wraparound period; values
  returned by ``ticks_ms()`` are always in ``[0 .. 2**29 - 1]``, and
  ``ticks_diff`` uses ring arithmetic so tests catch code that
  accidentally uses plain subtraction.

* :func:`sleep_ms` — real-clock sleep that adapts across runtimes
  (``time.sleep_ms`` on MicroPython, ``time.sleep`` on CPython /
  CircuitPython).  Test-only because real sleeps are forbidden in
  runner-tick library code; functional tests need them to assert
  "after N ms, X happened" on real hardware.

Example — tick-domain tests:
    ```python
    from chumicro_timing.testing import FakeTicks

    fake = FakeTicks()
    heartbeat = Heartbeat(period_ms=100, ticks=fake)
    fake.advance(100)
    assert heartbeat.poll(fake.ticks_ms()) is True
    ```
"""

__chumicro_test_support__ = True

import time

from chumicro_timing.ticks import TICKS_MAX, ticks_add, ticks_diff


def sleep_ms(duration_ms: int) -> None:
    """Real-clock sleep that picks the best available runtime API.

    Uses ``time.sleep_ms`` when present (MicroPython, CircuitPython)
    and falls back to ``time.sleep`` (CPython).
    """
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


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
            start_ms: Initial tick value.
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

        Args:
            end: Later tick value.
            start: Earlier tick value.

        Returns:
            Signed difference in milliseconds.
        """
        return ticks_diff(end, start)

    def ticks_add(self, ticks_val: int, delta: int) -> int:
        """Wraparound-safe addition of *delta* to a tick value.

        Args:
            ticks_val: Base tick value.
            delta: Milliseconds to add.

        Returns:
            Wrapped tick value in ``[0 .. 2**29 - 1]``.

        Raises:
            OverflowError: If *delta* is outside (-2**28 .. 2**28).
        """
        return ticks_add(ticks_val, delta)
