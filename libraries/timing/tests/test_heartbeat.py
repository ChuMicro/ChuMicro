"""Tests for the heartbeat periodic timing logic.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via the lightweight test harness).
"""

from chumicro_test_harness import raises
from chumicro_timing import Heartbeat
from chumicro_timing.testing import FakeTicks


def test_heartbeat_rejects_non_positive_periods() -> None:
    """Heartbeat periods must be positive to avoid undefined timing behavior."""
    with raises(ValueError):
        Heartbeat(0)

    with raises(ValueError):
        Heartbeat(-1)


def test_heartbeat_becomes_due_after_full_period() -> None:
    """The heartbeat should fire once the configured period has elapsed."""
    fake = FakeTicks()
    heartbeat = Heartbeat(period_ms=100, ticks=fake)

    now = fake.ticks_ms()
    assert heartbeat.is_due(now) is False
    assert heartbeat.poll(now) is False

    fake.advance(99)
    now = fake.ticks_ms()
    assert heartbeat.is_due(now) is False
    assert heartbeat.poll(now) is False

    fake.advance(1)
    now = fake.ticks_ms()
    assert heartbeat.is_due(now) is True
    assert heartbeat.poll(now) is True
    assert heartbeat.is_due(now) is False


def test_heartbeat_reset_restarts_the_schedule() -> None:
    """Reset should make the next due time relative to the reset moment."""
    fake = FakeTicks()
    heartbeat = Heartbeat(period_ms=50, ticks=fake)

    fake.advance(50)
    now = fake.ticks_ms()
    assert heartbeat.poll(now) is True

    fake.advance(10)
    now = fake.ticks_ms()
    heartbeat.reset(now)
    fake.advance(49)
    now = fake.ticks_ms()
    assert heartbeat.poll(now) is False

    fake.advance(1)
    now = fake.ticks_ms()
    assert heartbeat.poll(now) is True


def test_heartbeat_reports_period_configuration() -> None:
    """The configured heartbeat period should remain observable as public state."""
    heartbeat = Heartbeat(period_ms=250, ticks=FakeTicks())

    assert heartbeat.period_ms == 250


def test_heartbeat_shared_timestamp_prevents_drift() -> None:
    """Multiple heartbeats checking the same now_ms should see identical time."""
    fake = FakeTicks()
    hb_a = Heartbeat(period_ms=100, ticks=fake)
    hb_b = Heartbeat(period_ms=100, ticks=fake)

    fake.advance(100)
    now = fake.ticks_ms()
    assert hb_a.poll(now) is True
    assert hb_b.poll(now) is True


def test_heartbeat_poll_does_not_fire_before_period() -> None:
    """poll() should return False when called before the period elapses."""
    fake = FakeTicks()
    heartbeat = Heartbeat(period_ms=200, ticks=fake)

    fake.advance(199)
    now = fake.ticks_ms()
    assert heartbeat.poll(now) is False


def test_heartbeat_poll_fires_exactly_at_period() -> None:
    """poll() should return True at exactly the period boundary."""
    fake = FakeTicks()
    heartbeat = Heartbeat(period_ms=100, ticks=fake)

    fake.advance(100)
    now = fake.ticks_ms()
    assert heartbeat.poll(now) is True


def test_heartbeat_default_ticks_uses_real_clock() -> None:
    """Creating a Heartbeat without ticks= should use the real clock."""
    heartbeat = Heartbeat(period_ms=1000)

    # The real clock path stores the chumicro_timing.ticks submodule
    # and captures a live ticks_ms() reading at __init__.
    assert heartbeat._ticks is not None
    assert isinstance(heartbeat._last_beat_ms, int)
    assert heartbeat.period_ms == 1000


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
