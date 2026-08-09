"""Device-facing tests for tick arithmetic on real hardware.

Validates ticks_add, ticks_diff, forward progression, and wraparound
behavior using the actual runtime's monotonic clock source.
"""

from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import sleep_ms
from chumicro_timing.ticks import ticks_add, ticks_diff, ticks_ms


def test_ticks_progress_on_runtime() -> None:
    """The active runtime should expose forward-moving monotonic ticks."""
    start_ms = ticks_ms()
    sleep_ms(20)
    end_ms = ticks_ms()

    assert ticks_diff(end_ms, start_ms) >= 1


def test_ticks_ms_returns_non_negative() -> None:
    """ticks_ms should return a value in [0 .. 2**29 - 1]."""
    value = ticks_ms()
    assert value >= 0
    assert value < (1 << 29)


def test_ticks_diff_zero_for_same_value() -> None:
    """Diff of a value with itself should be zero."""
    now = ticks_ms()
    assert ticks_diff(now, now) == 0


def test_ticks_add_positive_delta() -> None:
    """Adding a positive delta should produce a forward-shifted tick."""
    base = ticks_ms()
    result = ticks_add(base, 500)
    assert ticks_diff(result, base) == 500


def test_ticks_add_negative_delta() -> None:
    """Adding a negative delta should produce a backward-shifted tick."""
    base = ticks_ms()
    result = ticks_add(base, -200)
    assert ticks_diff(result, base) == -200


def test_ticks_add_overflow_raises() -> None:
    """A delta at or beyond the half-period should raise OverflowError."""
    base = ticks_ms()
    half_period = 1 << 28
    with raises(OverflowError):
        ticks_add(base, half_period)


def test_ticks_diff_near_wraparound() -> None:
    """Diff should handle values that straddle the wrap boundary."""
    # Simulate: start near the max, end past the wrap point.
    near_max = (1 << 29) - 10
    past_wrap = ticks_add(near_max, 20)
    assert ticks_diff(past_wrap, near_max) == 20


def test_ticks_add_roundtrip() -> None:
    """add then diff should be symmetric for moderate deltas."""
    base = ticks_ms()
    for delta in [1, 100, 10000, 100000]:
        forwarded = ticks_add(base, delta)
        assert ticks_diff(forwarded, base) == delta
