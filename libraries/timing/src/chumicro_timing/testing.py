"""Host-test helpers: ``FakeTicks``, a clock that moves only when a test moves it, and a ``sleep_ms`` shim."""

__chumicro_test_support__ = True

import time

from chumicro_timing.ticks import TICKS_MAX, ticks_add, ticks_diff


def sleep_ms(duration_ms: int) -> None:
    """Block for ``duration_ms`` milliseconds on any runtime.

    It calls ``time.sleep_ms`` on CircuitPython and MicroPython and ``time.sleep`` on CPython.
    """
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


class FakeTicks:
    """A clock for host tests that stands still until the test moves it.

    ``FakeTicks`` has the ``ticks_ms``, ``ticks_add``, and ``ticks_diff`` of
    ``chumicro_timing.ticks``, so it goes anywhere a library takes ``ticks=``.  ``advance``
    moves it forward.  Its ``sleep_ms`` advances it and returns at once, so a
    ``Runner(ticks=FakeTicks())`` idles without stalling the test.

    Args:
        start_ms: The first reading ``ticks_ms()`` returns.
    """

    def __init__(self, start_ms: int = 0) -> None:
        self._current_ms = start_ms

    def advance(self, amount_ms: int) -> None:
        """Move the clock forward by ``amount_ms`` milliseconds."""
        self._current_ms += amount_ms

    def sleep_ms(self, duration_ms: int) -> None:
        """Move the clock forward by ``duration_ms`` milliseconds and return at once."""
        self._current_ms += duration_ms

    def ticks_ms(self) -> int:
        """Return the current reading, rolled over into the 0 to ``TICKS_MAX`` tick range."""
        return self._current_ms & TICKS_MAX

    def ticks_diff(self, end: int, start: int) -> int:
        """Return the signed milliseconds from ``start`` to ``end``, as ``ticks_diff`` does."""
        return ticks_diff(end, start)

    def ticks_add(self, ticks_val: int, delta: int) -> int:
        """Return the tick ``delta`` milliseconds after ``ticks_val``, as ``ticks_add`` does."""
        return ticks_add(ticks_val, delta)
