"""Cross-runtime tests for tick arithmetic helpers.

These tests use only plain asserts and the harness ``raises()`` helper,
so they run on CPython (via pytest) and on MicroPython/CircuitPython
(via the lightweight test harness).
"""

import chumicro_timing.ticks as ticks_module
from chumicro_test_harness import raises

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
