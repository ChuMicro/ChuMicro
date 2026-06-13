"""Cross-runtime tests for tick arithmetic helpers.

These tests use only plain asserts and the harness ``raises()`` helper,
so they run on CPython (via pytest) and on MicroPython/CircuitPython
(via the lightweight test harness).
"""

import chumicro_timing.ticks as ticks_module
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

# -- ticks_diff ring arithmetic --


def test_ticks_diff_forward() -> None:
    """A normal forward difference should return the expected positive value."""
    assert ticks_module.ticks_diff(150, 100) == 50


def test_ticks_diff_handles_wraparound() -> None:
    """A difference across the wrap boundary should be computed correctly."""
    period = 1 << 29
    start = period - 10
    end = 5

    assert ticks_module.ticks_diff(end, start) == 15


def test_ticks_diff_returns_negative_for_past_value() -> None:
    """A diff where the end is before the start should return a negative value."""
    assert ticks_module.ticks_diff(100, 150) == -50


# -- ticks_add --


def test_ticks_add_normal() -> None:
    """Adding a delta within range should return a plain sum."""
    assert ticks_module.ticks_add(100, 50) == 150


def test_ticks_add_wraps() -> None:
    """Adding past the period boundary should wrap correctly."""
    period = 1 << 29
    assert ticks_module.ticks_add(period - 10, 20) == 10


def test_ticks_add_rejects_overflow() -> None:
    """Deltas at or beyond the half-period should raise OverflowError."""
    halfperiod = 1 << 28

    with raises(OverflowError):
        ticks_module.ticks_add(0, halfperiod)

    with raises(OverflowError):
        ticks_module.ticks_add(0, -halfperiod)


# -- ticks_ms masking (no monkeypatch — uses the live runtime source) --


def test_ticks_ms_returns_non_negative() -> None:
    """ticks_ms() should return a non-negative integer on any runtime."""
    result = ticks_module.ticks_ms()
    assert isinstance(result, int)
    assert result >= 0


def test_ticks_ms_fits_in_period() -> None:
    """ticks_ms() should be masked to the 2**29 period."""
    period = 1 << 29
    result = ticks_module.ticks_ms()
    assert 0 <= result < period


# -- FakeTicks.sleep_ms advances the fake clock --


def test_fake_ticks_sleep_ms_advances_reading() -> None:
    """FakeTicks.sleep_ms moves ticks_ms() forward by the slept duration,
    matching advance() — an honest fake where sleeping makes time pass."""
    fake = FakeTicks(start_ms=100)
    fake.sleep_ms(250)
    assert fake.ticks_ms() == 350


def test_fake_ticks_sleep_ms_folds_into_wrap_range() -> None:
    """A sleep that crosses the 2**29 wrap boundary masks like advance():
    ticks_ms() stays in [0, TICKS_MAX] and reads the wrapped value."""
    fake = FakeTicks(start_ms=ticks_module.TICKS_MAX - 10)
    fake.sleep_ms(30)
    # (TICKS_MAX - 10 + 30) & TICKS_MAX == 19 after wrapping past TICKS_MAX.
    assert fake.ticks_ms() == 19
