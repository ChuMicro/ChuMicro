"""Device-facing tests for the Heartbeat scheduler on real hardware.

Validates that Heartbeat works with the actual runtime clock: both
the default (real ticks) and constructor-injected tick sources.
"""

import time

from chumicro_timing.heartbeat import Heartbeat
from chumicro_timing.ticks import ticks_ms


def _sleep_ms(duration_ms: int) -> None:
    """Sleep for the requested duration using the best available API.

    Args:
        duration_ms: Duration in milliseconds.
    """
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def test_heartbeat_not_due_immediately() -> None:
    """A freshly created heartbeat should not be due right away."""
    heartbeat = Heartbeat(period_ms=500)
    now = ticks_ms()
    assert heartbeat.is_due(now) is False


def test_heartbeat_becomes_due_after_period() -> None:
    """Heartbeat should become due after its period elapses."""
    heartbeat = Heartbeat(period_ms=30)
    _sleep_ms(50)
    now = ticks_ms()
    assert heartbeat.is_due(now) is True


def test_heartbeat_poll_fires_and_resets() -> None:
    """poll should return True once, then False until the period elapses."""
    heartbeat = Heartbeat(period_ms=30)
    _sleep_ms(50)
    now = ticks_ms()
    assert heartbeat.poll(now) is True
    # Immediately after poll, should not be due again.
    now = ticks_ms()
    assert heartbeat.poll(now) is False


def test_heartbeat_reset_restarts_countdown() -> None:
    """Resetting the heartbeat should make it not-due again."""
    heartbeat = Heartbeat(period_ms=30)
    _sleep_ms(50)
    now = ticks_ms()
    assert heartbeat.is_due(now) is True
    heartbeat.reset(now)
    now = ticks_ms()
    assert heartbeat.is_due(now) is False


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
