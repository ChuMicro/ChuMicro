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


def test_heartbeat_reset_restarts_the_schedule():
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


def test_heartbeat_reports_period_configuration():
    """The configured heartbeat period should remain observable as public state."""
    heartbeat = Heartbeat(period_ms=250, ticks=FakeTicks())

    assert heartbeat.period_ms == 250


# -- service() / serviceable pattern --


def test_heartbeat_service_emits_tick_when_due():
    """service() should emit the configured event_type into the sink when a beat is due."""
    fake_ticks = FakeTicks()
    heartbeat = Heartbeat(
        period_ms=100, ticks=fake_ticks, event_type=Heartbeat.EVENT_TICK,
    )
    events = []

    class _ListSink:
        def emit(self, source, event_type, data=None):
            events.append((source, event_type, data))

    sink = _ListSink()
    fake_ticks.advance(100)
    heartbeat.service(sink)

    assert len(events) == 1
    assert events[0][0] is heartbeat
    assert events[0][1] == Heartbeat.EVENT_TICK
    assert events[0][2] is None


def test_heartbeat_service_does_not_emit_when_not_due():
    """service() should emit nothing when the period has not elapsed."""
    fake_ticks = FakeTicks()
    heartbeat = Heartbeat(
        period_ms=100, ticks=fake_ticks, event_type=Heartbeat.EVENT_TICK,
    )
    events = []

    class _ListSink:
        def emit(self, source, event_type, data=None):
            events.append(1)

    heartbeat.service(_ListSink())

    assert events == []


def test_heartbeat_event_tick_constant():
    """EVENT_TICK should be a stable string constant."""
    assert Heartbeat.EVENT_TICK == "heartbeat.tick"


# -- custom event_type --


def test_heartbeat_event_type_defaults_to_none():
    """Without an explicit event_type, the property should be None."""
    heartbeat = Heartbeat(period_ms=100, ticks=FakeTicks())

    assert heartbeat.event_type is None


def test_heartbeat_service_raises_without_event_type():
    """service() should raise RuntimeError when no event_type was provided."""
    fake_ticks = FakeTicks()
    heartbeat = Heartbeat(period_ms=100, ticks=fake_ticks)

    class _ListSink:
        def emit(self, source, event_type, data=None):
            pass

    fake_ticks.advance(100)
    with raises(RuntimeError):
        heartbeat.service(_ListSink())


def test_heartbeat_custom_event_type():
    """A custom event_type should be used by service() instead of EVENT_TICK."""
    fake_ticks = FakeTicks()
    heartbeat = Heartbeat(period_ms=100, ticks=fake_ticks, event_type="led.blink")
    events = []

    class _ListSink:
        def emit(self, source, event_type, data=None):
            events.append((source, event_type))

    fake_ticks.advance(100)
    heartbeat.service(_ListSink())

    assert len(events) == 1
    assert events[0][0] is heartbeat
    assert events[0][1] == "led.blink"


def test_heartbeat_custom_event_type_property():
    """The event_type property should reflect the configured value."""
    heartbeat = Heartbeat(period_ms=50, ticks=FakeTicks(), event_type="sensor.read")

    assert heartbeat.event_type == "sensor.read"


def test_two_heartbeats_emit_distinct_event_types():
    """Two heartbeats with different event_types should emit distinguishable events."""
    fake_ticks = FakeTicks()
    hb_a = Heartbeat(period_ms=100, ticks=fake_ticks, event_type="a.tick")
    hb_b = Heartbeat(period_ms=100, ticks=fake_ticks, event_type="b.tick")
    events = []

    class _ListSink:
        def emit(self, source, event_type, data=None):
            events.append(event_type)

    fake_ticks.advance(100)
    hb_a.service(_ListSink())
    hb_b.service(_ListSink())

    assert events == ["a.tick", "b.tick"]


