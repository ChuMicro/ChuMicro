"""Device-facing tests for the Heartbeat scheduler on real hardware.

Validates that Heartbeat works with the actual runtime clock: both
the default (real ticks) and constructor-injected tick sources.
"""

from chumicro_timing.heartbeat import Heartbeat
from chumicro_timing.testing import sleep_ms
from chumicro_timing.ticks import ticks_ms


def test_heartbeat_not_due_immediately() -> None:
    """A freshly created heartbeat should not fire right away."""
    heartbeat = Heartbeat(period_ms=500)
    now = ticks_ms()
    assert heartbeat.poll(now) is False


def test_heartbeat_poll_fires_and_resets() -> None:
    """poll should return True once, then False until the period elapses."""
    heartbeat = Heartbeat(period_ms=30)
    sleep_ms(50)
    now = ticks_ms()
    assert heartbeat.poll(now) is True
    # Immediately after poll, should not be due again.
    now = ticks_ms()
    assert heartbeat.poll(now) is False


def test_heartbeat_reset_restarts_countdown() -> None:
    """Resetting the heartbeat should make it not-due again."""
    heartbeat = Heartbeat(period_ms=30)
    sleep_ms(50)
    now = ticks_ms()
    heartbeat.reset(now)
    # Re-reading now without sleeping means the period hasn't elapsed
    # since reset — poll must not fire.
    now = ticks_ms()
    assert heartbeat.poll(now) is False


def test_heartbeat_period_property() -> None:
    """period_ms property should reflect the configured period."""
    heartbeat = Heartbeat(period_ms=250)
    assert heartbeat.period_ms == 250


def test_heartbeat_rejects_zero_period() -> None:
    """Heartbeat should reject a zero period."""
    raised = False
    try:
        Heartbeat(period_ms=0)
    except ValueError:
        raised = True
    assert raised is True


def test_heartbeat_rejects_negative_period() -> None:
    """Heartbeat should reject a negative period."""
    raised = False
    try:
        Heartbeat(period_ms=-100)
    except ValueError:
        raised = True
    assert raised is True
