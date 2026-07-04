"""Cross-runtime tests for the wait value objects: Deadline, Rate.

Plain asserts plus the harness ``raises()`` helper, so they run on
CPython (via pytest) and on MicroPython/CircuitPython (via the
lightweight test harness).
"""

from chumicro_test_harness import raises
from chumicro_timing import Deadline, Rate
from chumicro_timing.ticks import TICKS_HALFPERIOD

# -- Deadline --------------------------------------------------------


def test_deadline_arms_from_now_and_reports_period() -> None:
    """A Deadline arms period_ms past the supplied now_ms and exposes period_ms."""
    deadline = Deadline(100, 1000)
    assert deadline.period_ms == 100
    assert deadline.expired(1099) is False
    assert deadline.expired(1100) is True


def test_deadline_expired_is_true_at_and_after_the_due_tick() -> None:
    """expired() flips True exactly at the due tick and stays True past it."""
    deadline = Deadline(50, 0)
    assert deadline.expired(49) is False
    assert deadline.expired(50) is True
    assert deadline.expired(500) is True


def test_deadline_remaining_counts_down_and_clamps_at_zero() -> None:
    """remaining() is the ms until due, clamped at 0 once the deadline passes."""
    deadline = Deadline(100, 0)
    assert deadline.remaining(0) == 100
    assert deadline.remaining(40) == 60
    assert deadline.remaining(100) == 0
    assert deadline.remaining(250) == 0


def test_deadline_reset_re_arms_the_same_period() -> None:
    """reset() re-arms the same period_ms from a fresh now_ms."""
    deadline = Deadline(50, 0)
    assert deadline.expired(50) is True
    deadline.reset(200)
    assert deadline.expired(249) is False
    assert deadline.expired(250) is True


def test_deadline_survives_tick_wraparound() -> None:
    """A deadline armed just before the 2**29 wrap expires correctly past it."""
    period = 1 << 29
    deadline = Deadline(100, period - 50)
    # 40 ms in (still before wrap): not yet due.
    assert deadline.expired((period - 10) & (period - 1)) is False
    # 100 ms in (50 ms past the wrap): due.
    assert deadline.expired(50) is True


# -- Rate ------------------------------------------------------------


def test_rate_rejects_non_positive_periods() -> None:
    """Rate periods must be positive to avoid undefined timing behavior."""
    with raises(ValueError):
        Rate(0, 0)
    with raises(ValueError):
        Rate(-1, 0)


def test_rate_rejects_periods_at_or_above_half_the_ring() -> None:
    """A period >= TICKS_HALFPERIOD can never fire, so it raises instead."""
    with raises(ValueError):
        Rate(TICKS_HALFPERIOD, 0)
    with raises(ValueError):
        Rate(TICKS_HALFPERIOD + 1, 0)


def test_rate_accepts_period_just_below_half_the_ring() -> None:
    """The largest representable period (TICKS_HALFPERIOD - 1) is accepted."""
    rate = Rate(TICKS_HALFPERIOD - 1, 0)
    assert rate.period_ms == TICKS_HALFPERIOD - 1


def test_rate_becomes_due_once_per_period() -> None:
    """due() fires at the boundary and only once at the same now_ms."""
    rate = Rate(100, 0)
    assert rate.due(99) is False
    assert rate.due(100) is True
    assert rate.due(100) is False


def test_rate_is_phase_aligned_not_drift() -> None:
    """After a late fire, the next fire stays on the original cadence."""
    rate = Rate(100, 0)
    assert rate.due(105) is True
    # Next fire is at 200 (scheduled + period), not 205 (now + period).
    assert rate.due(199) is False
    assert rate.due(200) is True


def test_rate_drops_missed_periods_after_a_long_gap() -> None:
    """A gap longer than one period fires once and re-phases to the next slot."""
    rate = Rate(100, 0)
    # 2.5 periods late: only one fire, then re-phased to 300.
    assert rate.due(250) is True
    assert rate.due(250) is False
    assert rate.due(299) is False
    assert rate.due(300) is True


def test_rate_reset_restarts_the_cadence() -> None:
    """reset() re-anchors so the next fire lands one period after now_ms."""
    rate = Rate(50, 0)
    assert rate.due(50) is True
    rate.reset(1000)
    assert rate.due(1049) is False
    assert rate.due(1050) is True


def test_rate_fires_across_tick_wraparound() -> None:
    """due() fires when the period elapses across the 2**29 wrap boundary."""
    period = 1 << 29
    rate = Rate(100, period - 50)
    assert rate.due(50) is True
