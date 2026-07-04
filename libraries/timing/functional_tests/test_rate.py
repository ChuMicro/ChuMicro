"""Device-facing tests for the Rate cadence poller on real hardware.

Validates that Rate works with the actual runtime clock: threading a
live ``ticks_ms()`` reading through construction and ``due()``.
"""

from chumicro_timing import Rate
from chumicro_timing.testing import sleep_ms
from chumicro_timing.ticks import ticks_ms


def test_rate_not_due_immediately() -> None:
    """A freshly created rate should not fire right away."""
    rate = Rate(500, ticks_ms())
    assert rate.due(ticks_ms()) is False


def test_rate_due_fires_and_re_phases() -> None:
    """due should return True once, then False until the period elapses."""
    rate = Rate(30, ticks_ms())
    sleep_ms(50)
    assert rate.due(ticks_ms()) is True
    # Immediately after the fire, should not be due again.
    assert rate.due(ticks_ms()) is False


def test_rate_reset_restarts_countdown() -> None:
    """Resetting the rate should make it not-due again."""
    rate = Rate(30, ticks_ms())
    sleep_ms(50)
    rate.reset(ticks_ms())
    # Re-reading now without sleeping means the period hasn't elapsed
    # since reset — due must not fire.
    assert rate.due(ticks_ms()) is False


def test_rate_period_attribute() -> None:
    """period_ms should reflect the configured period."""
    rate = Rate(250, ticks_ms())
    assert rate.period_ms == 250


def test_rate_rejects_zero_period() -> None:
    """Rate should reject a zero period."""
    raised = False
    try:
        Rate(0, ticks_ms())
    except ValueError:
        raised = True
    assert raised is True


def test_rate_rejects_negative_period() -> None:
    """Rate should reject a negative period."""
    raised = False
    try:
        Rate(-100, ticks_ms())
    except ValueError:
        raised = True
    assert raised is True
