"""Hands tests a ``sleep_ms`` shim and a ``FakeTicks`` they can drive by hand."""

__chumicro_test_support__ = True

import time

from chumicro_timing.ticks import TICKS_MAX, ticks_add, ticks_diff


def sleep_ms(duration_ms: int) -> None:
    """Sleeps for ``duration_ms``, picking ``time.sleep_ms`` when the runtime offers it."""
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


class FakeTicks:
    """Stands in for the real tick source; tests step ``_current_ms`` forward with ``advance``."""

    def __init__(self, start_ms: int = 0) -> None:
        """Pins the initial tick reading to ``start_ms``."""
        self._current_ms = start_ms

    def advance(self, amount_ms: int) -> None:
        """Bumps ``_current_ms`` by ``amount_ms`` without masking so tests can wrap past."""
        self._current_ms += amount_ms

    def ticks_ms(self) -> int:
        """Reads ``_current_ms`` masked into the 29-bit wrap range, like production ``ticks_ms``."""
        return self._current_ms & TICKS_MAX

    def ticks_diff(self, end: int, start: int) -> int:
        """Hands back the production ``ticks_diff`` so wrap arithmetic stays identical in tests."""
        return ticks_diff(end, start)

    def ticks_add(self, ticks_val: int, delta: int) -> int:
        """Hands back the production ``ticks_add`` so wrap arithmetic stays identical in tests."""
        return ticks_add(ticks_val, delta)
