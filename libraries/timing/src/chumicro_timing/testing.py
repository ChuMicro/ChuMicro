"""Test-support helpers: a ``sleep_ms`` shim and a hand-driven ``FakeTicks``."""

__chumicro_test_support__ = True

import time

from chumicro_timing.ticks import TICKS_MAX, ticks_add, ticks_diff


def sleep_ms(duration_ms: int) -> None:
    """Sleeps for ``duration_ms`` via ``time.sleep_ms`` when present, otherwise ``time.sleep`` in seconds."""
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


class FakeTicks:
    """Hand-driven ticks source; ``ticks_ms()`` only changes when ``advance()`` is called."""

    def __init__(self, start_ms: int = 0) -> None:
        self._current_ms = start_ms

    def advance(self, amount_ms: int) -> None:
        """Bumps the current reading by ``amount_ms``."""
        self._current_ms += amount_ms

    def sleep_ms(self, duration_ms: int) -> None:
        """Advance the fake clock by ``duration_ms`` instead of sleeping for real."""
        self._current_ms += duration_ms

    def ticks_ms(self) -> int:
        """Returns the current reading masked into the wrap-safe 29-bit range."""
        return self._current_ms & TICKS_MAX

    def ticks_diff(self, end: int, start: int) -> int:
        """Returns the signed wrap-safe difference ``end - start``."""
        return ticks_diff(end, start)

    def ticks_add(self, ticks_val: int, delta: int) -> int:
        """Returns ``ticks_val + delta`` folded into the wrap-safe range."""
        return ticks_add(ticks_val, delta)
