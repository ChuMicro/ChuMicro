"""Tests for the heartbeat periodic timing logic.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via the lightweight test harness).
"""

from chumicro_test_harness import raises
from chumicro_timing import Heartbeat
from chumicro_timing.testing import FakeTicks


def test_heartbeat_rejects_non_positive_periods():
    """Heartbeat periods must be positive to avoid undefined timing behavior."""
    with raises(ValueError):
        Heartbeat(0)

    with raises(ValueError):
        Heartbeat(-1)


def test_heartbeat_becomes_due_after_full_period():
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


def test_heartbeat_reset_restarts_the_schedule():
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


def test_heartbeat_reports_period_configuration():
    """The configured heartbeat period should remain observable as public state."""
    heartbeat = Heartbeat(period_ms=250, ticks=FakeTicks())

    assert heartbeat.period_ms == 250


def test_heartbeat_shared_timestamp_prevents_drift():
    """Multiple heartbeats checking the same now_ms should see identical time."""
    fake = FakeTicks()
    hb_a = Heartbeat(period_ms=100, ticks=fake)
    hb_b = Heartbeat(period_ms=100, ticks=fake)

    fake.advance(100)
    now = fake.ticks_ms()
    assert hb_a.poll(now) is True
    assert hb_b.poll(now) is True


def test_heartbeat_poll_does_not_fire_before_period():
    """poll() should return False when called before the period elapses."""
    fake = FakeTicks()
    heartbeat = Heartbeat(period_ms=200, ticks=fake)

    fake.advance(199)
    now = fake.ticks_ms()
    assert heartbeat.poll(now) is False


def test_heartbeat_poll_fires_exactly_at_period():
    """poll() should return True at exactly the period boundary."""
    fake = FakeTicks()
    heartbeat = Heartbeat(period_ms=100, ticks=fake)

    fake.advance(100)
    now = fake.ticks_ms()
    assert heartbeat.poll(now) is True
