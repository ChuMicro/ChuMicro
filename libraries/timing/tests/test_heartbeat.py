"""Tests for the heartbeat periodic timing logic."""

from __future__ import annotations

import pytest
from chumicro_timing import Heartbeat
from mocks.fake_ticks import FakeTicks


def test_heartbeat_rejects_non_positive_periods() -> None:
    """Heartbeat periods must be positive to avoid undefined timing behavior."""
    with pytest.raises(ValueError):
        Heartbeat(0)

    with pytest.raises(ValueError):
        Heartbeat(-1)


def test_heartbeat_becomes_due_after_full_period() -> None:
    """The heartbeat should fire once the configured period has elapsed."""
    fake_ticks = FakeTicks()
    heartbeat = Heartbeat(period_ms=100, ticks=fake_ticks)

    assert heartbeat.is_due() is False
    assert heartbeat.poll() is False

    fake_ticks.advance(99)
    assert heartbeat.is_due() is False
    assert heartbeat.poll() is False

    fake_ticks.advance(1)
    assert heartbeat.is_due() is True
    assert heartbeat.poll() is True
    assert heartbeat.is_due() is False


def test_heartbeat_reset_restarts_the_schedule() -> None:
    """Reset should make the next due time relative to the reset moment."""
    fake_ticks = FakeTicks()
    heartbeat = Heartbeat(period_ms=50, ticks=fake_ticks)

    fake_ticks.advance(50)
    assert heartbeat.poll() is True

    fake_ticks.advance(10)
    heartbeat.reset()
    fake_ticks.advance(49)
    assert heartbeat.poll() is False

    fake_ticks.advance(1)
    assert heartbeat.poll() is True


def test_heartbeat_reports_period_configuration() -> None:
    """The configured heartbeat period should remain observable as public state."""
    heartbeat = Heartbeat(period_ms=250, ticks=FakeTicks())

    assert heartbeat.period_ms == 250

