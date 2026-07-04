"""Cross-runtime tests for the test-support helpers: FakeTicks and sleep_ms.

Plain asserts plus the harness ``raises()`` helper, so they run on
CPython (via pytest) and on MicroPython/CircuitPython (via the
lightweight test harness).
"""

from chumicro_test_harness import raises
from chumicro_timing import ticks_diff, ticks_ms
from chumicro_timing.testing import FakeTicks, sleep_ms


def test_sleep_ms_advances_the_clock() -> None:
    """sleep_ms(5) returns within 500 ms with non-negative elapsed ticks."""
    start = ticks_ms()
    sleep_ms(5)
    elapsed = ticks_diff(ticks_ms(), start)
    assert elapsed >= 0  # never negative
    assert elapsed < 500  # didn't block forever


def test_fake_ticks_add() -> None:
    """FakeTicks.ticks_add should return a wrapped sum."""
    fake = FakeTicks()
    assert fake.ticks_add(100, 50) == 150
    assert fake.ticks_add(0, 0) == 0
    # Modular arithmetic: result wraps at 2**29.
    period = 1 << 29
    assert fake.ticks_add(period - 10, 20) == 10


def test_fake_ticks_add_rejects_overflow() -> None:
    """FakeTicks.ticks_add should reject deltas at or beyond half-period."""
    fake = FakeTicks()
    halfperiod = 1 << 28

    with raises(OverflowError):
        fake.ticks_add(0, halfperiod)

    with raises(OverflowError):
        fake.ticks_add(0, -halfperiod)


def test_fake_ticks_ms_wraps_at_period() -> None:
    """FakeTicks.ticks_ms should mask to [0 .. 2**29 - 1]."""
    period = 1 << 29
    fake = FakeTicks(start_ms=period - 1)
    assert fake.ticks_ms() == period - 1

    fake.advance(1)
    assert fake.ticks_ms() == 0  # wrapped

    fake.advance(1)
    assert fake.ticks_ms() == 1


def test_fake_ticks_diff_handles_wraparound() -> None:
    """FakeTicks.ticks_diff should use ring arithmetic like the real impl."""
    period = 1 << 29
    # Normal forward difference.
    fake = FakeTicks()
    assert fake.ticks_diff(100, 50) == 50

    # Wraparound: end < start numerically, but logically end is later.
    end = 10
    start = period - 10
    assert fake.ticks_diff(end, start) == 20
