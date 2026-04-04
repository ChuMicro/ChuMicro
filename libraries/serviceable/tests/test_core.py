"""Tests for the core serviceable-pattern abstractions.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via the lightweight test harness).
"""

from chumicro_serviceable import (
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    Event,
    EventQueueSink,
    HandlerHandle,
    ServiceRunner,
    SimpleEventDispatcher,
)
from chumicro_serviceable.testing import FakeEventSink
from chumicro_timing.testing import FakeTicks

# -- Event --


def test_event_stores_fields():
    """Event should store source, event_type, and data."""
    sentinel = object()
    event = Event(source=sentinel, event_type="tick", data=42)

    assert event.source is sentinel
    assert event.event_type == "tick"
    assert event.data == 42


def test_event_data_defaults_to_none():
    """Data should default to None when omitted."""
    event = Event(source="s", event_type="t")

    assert event.data is None


def test_event_repr():
    """Repr should include event_type, source, and data."""
    event = Event(source="src", event_type="tick", data=1)

    r = repr(event)
    assert "tick" in r
    assert "src" in r


# -- EventQueueSink --


def test_sink_starts_empty():
    """A new sink should have no events."""
    sink = EventQueueSink(max_size=4)

    assert not sink.has_events()
    assert len(sink) == 0
    assert sink.pop() is None


def test_sink_emit_and_pop():
    """Emitted events should come back in FIFO order."""
    sink = EventQueueSink(max_size=4)
    sink.emit("a", "t1")
    sink.emit("b", "t2", data=99)

    assert len(sink) == 2

    e1 = sink.pop()
    assert e1.source == "a"
    assert e1.event_type == "t1"
    assert e1.data is None

    e2 = sink.pop()
    assert e2.source == "b"
    assert e2.data == 99

    assert not sink.has_events()


def test_sink_returns_false_when_full():
    """Emit should return False when the buffer is at capacity."""
    sink = EventQueueSink(max_size=2)

    assert sink.emit("a", "t") is True
    assert sink.emit("b", "t") is True
    assert sink.emit("c", "t") is False
    assert len(sink) == 2


def test_sink_wraps_around():
    """The ring buffer should reuse slots after pop."""
    sink = EventQueueSink(max_size=2)
    sink.emit("a", "first")
    sink.pop()
    sink.emit("b", "second")
    sink.emit("c", "third")

    assert len(sink) == 2
    assert sink.pop().source == "b"
    assert sink.pop().source == "c"


def test_sink_clear():
    """Clear should discard all pending events."""
    sink = EventQueueSink(max_size=4)
    sink.emit("a", "t")
    sink.emit("b", "t")
    sink.clear()

    assert not sink.has_events()
    assert len(sink) == 0
    assert sink.pop() is None


# -- Priority constants --


def test_priority_ordering():
    """Priority constants should be ordered: CRITICAL < HIGH < NORMAL < LOW."""
    assert PRIORITY_CRITICAL < PRIORITY_HIGH < PRIORITY_NORMAL < PRIORITY_LOW


# -- SimpleEventDispatcher: basic routing --


def test_dispatcher_routes_to_handler():
    """Dispatch should call the handler registered for the event type."""
    received = []
    dispatcher = SimpleEventDispatcher()
    dispatcher.register("tick", lambda e: received.append(e))

    event = Event("src", "tick")
    dispatcher.dispatch(event)

    assert len(received) == 1
    assert received[0] is event


def test_dispatcher_ignores_unregistered_types():
    """Dispatch should silently ignore events with no handler."""
    dispatcher = SimpleEventDispatcher()
    dispatcher.dispatch(Event("src", "unknown"))  # should not raise


def test_dispatcher_unregister():
    """Unregister should remove a previously registered handler."""
    called = []
    dispatcher = SimpleEventDispatcher()
    dispatcher.register("tick", lambda e: called.append(1))
    dispatcher.unregister("tick")
    dispatcher.dispatch(Event("src", "tick"))

    assert called == []


def test_dispatcher_unregister_missing_is_safe():
    """Unregistering a type that was never registered should not raise."""
    dispatcher = SimpleEventDispatcher()
    dispatcher.unregister("nonexistent")  # should not raise


# -- HandlerHandle --


def test_register_returns_handle():
    """register() should return a HandlerHandle."""
    dispatcher = SimpleEventDispatcher()
    handle = dispatcher.register("tick", lambda e: None)

    assert isinstance(handle, HandlerHandle)


def test_handle_event_type():
    """Handle should expose the event type."""
    dispatcher = SimpleEventDispatcher()
    handle = dispatcher.register("tick", lambda e: None)

    assert handle.event_type == "tick"


def test_handle_default_priority():
    """Default priority should be PRIORITY_NORMAL."""
    dispatcher = SimpleEventDispatcher()
    handle = dispatcher.register("tick", lambda e: None)

    assert handle.priority == PRIORITY_NORMAL


def test_handle_custom_priority():
    """Register with a custom priority should be reflected on the handle."""
    dispatcher = SimpleEventDispatcher()
    handle = dispatcher.register("tick", lambda e: None, priority=PRIORITY_HIGH)

    assert handle.priority == PRIORITY_HIGH


def test_handle_active_when_registered():
    """Handle should report active when registered."""
    dispatcher = SimpleEventDispatcher()
    handle = dispatcher.register("tick", lambda e: None)

    assert handle.active is True


def test_handle_inactive_after_unregister():
    """Handle should report inactive after unregister()."""
    dispatcher = SimpleEventDispatcher()
    handle = dispatcher.register("tick", lambda e: None)
    handle.unregister()

    assert handle.active is False


def test_handle_unregister_stops_dispatch():
    """After handle.unregister(), dispatch should not call the handler."""
    called = []
    dispatcher = SimpleEventDispatcher()
    handle = dispatcher.register("tick", lambda e: called.append(1))
    handle.unregister()
    dispatcher.dispatch(Event("src", "tick"))

    assert called == []


def test_handle_unregister_idempotent():
    """Calling unregister() twice should not raise."""
    dispatcher = SimpleEventDispatcher()
    handle = dispatcher.register("tick", lambda e: None)
    handle.unregister()
    handle.unregister()  # should not raise


def test_handle_set_priority():
    """set_priority() should update the handle's priority."""
    dispatcher = SimpleEventDispatcher()
    handle = dispatcher.register("tick", lambda e: None)
    handle.set_priority(PRIORITY_LOW)

    assert handle.priority == PRIORITY_LOW


def test_handle_period_ms_none_by_default():
    """period_ms should be None when no heartbeat is configured."""
    dispatcher = SimpleEventDispatcher()
    handle = dispatcher.register("tick", lambda e: None)

    assert handle.period_ms is None


def test_handle_repr():
    """Handle repr should include event type and status."""
    dispatcher = SimpleEventDispatcher()
    handle = dispatcher.register("tick", lambda e: None)

    r = repr(handle)
    assert "tick" in r
    assert "active" in r


def test_handle_repr_after_unregister():
    """Handle repr should show inactive after unregister."""
    dispatcher = SimpleEventDispatcher()
    handle = dispatcher.register("tick", lambda e: None)
    handle.unregister()

    assert "inactive" in repr(handle)


def test_reregister_replaces_handler():
    """Re-registering the same event type should replace the handler."""
    first_called = []
    second_called = []
    dispatcher = SimpleEventDispatcher()
    dispatcher.register("tick", lambda e: first_called.append(1))
    dispatcher.register("tick", lambda e: second_called.append(1))
    dispatcher.dispatch(Event("src", "tick"))

    assert first_called == []
    assert second_called == [1]


def test_reregister_deactivates_old_handle():
    """Re-registering should deactivate the old handle."""
    dispatcher = SimpleEventDispatcher()
    old_handle = dispatcher.register("tick", lambda e: None)
    dispatcher.register("tick", lambda e: None)

    assert old_handle.active is False


# -- Heartbeat-integrated handlers --


def test_heartbeat_handler_period_ms():
    """Handle should expose the configured heartbeat period."""
    fake = FakeTicks()
    dispatcher = SimpleEventDispatcher(ticks=fake)
    handle = dispatcher.register("tick", lambda e: None, period_ms=200)

    assert handle.period_ms == 200


def test_heartbeat_handler_fires_when_due():
    """poll_heartbeats() should emit an event when the heartbeat period elapses."""
    fake = FakeTicks()
    dispatcher = SimpleEventDispatcher(ticks=fake)
    received = []
    dispatcher.register("pulse", lambda e: received.append(e.event_type),
                        period_ms=100)

    sink = EventQueueSink(max_size=8)

    # Not due yet.
    fake.advance(50)
    dispatcher.poll_heartbeats(fake.ticks_ms(), sink)
    assert len(sink) == 0

    # Now due.
    fake.advance(50)
    dispatcher.poll_heartbeats(fake.ticks_ms(), sink)
    assert len(sink) == 1
    assert sink.pop().event_type == "pulse"


def test_heartbeat_handler_does_not_fire_early():
    """poll_heartbeats() should not emit before the period elapses."""
    fake = FakeTicks()
    dispatcher = SimpleEventDispatcher(ticks=fake)
    dispatcher.register("pulse", lambda e: None, period_ms=100)
    sink = EventQueueSink(max_size=4)

    fake.advance(99)
    dispatcher.poll_heartbeats(fake.ticks_ms(), sink)

    assert len(sink) == 0


def test_heartbeat_handler_repeats():
    """Heartbeat should fire again after another period elapses."""
    fake = FakeTicks()
    dispatcher = SimpleEventDispatcher(ticks=fake)
    dispatcher.register("pulse", lambda e: None, period_ms=100)
    sink = EventQueueSink(max_size=8)

    fake.advance(100)
    dispatcher.poll_heartbeats(fake.ticks_ms(), sink)
    assert len(sink) == 1
    sink.pop()

    fake.advance(100)
    dispatcher.poll_heartbeats(fake.ticks_ms(), sink)
    assert len(sink) == 1


def test_multiple_heartbeat_handlers():
    """Multiple heartbeat handlers with different periods should fire independently."""
    fake = FakeTicks()
    dispatcher = SimpleEventDispatcher(ticks=fake)
    dispatcher.register("fast", lambda e: None, period_ms=50)
    dispatcher.register("slow", lambda e: None, period_ms=200)
    sink = EventQueueSink(max_size=8)

    # At 50ms: fast fires, slow does not.
    fake.advance(50)
    dispatcher.poll_heartbeats(fake.ticks_ms(), sink)
    assert len(sink) == 1
    assert sink.pop().event_type == "fast"

    # At 100ms: fast fires again, slow still not.
    fake.advance(50)
    dispatcher.poll_heartbeats(fake.ticks_ms(), sink)
    assert len(sink) == 1
    assert sink.pop().event_type == "fast"

    # At 200ms: both fire.
    fake.advance(100)
    dispatcher.poll_heartbeats(fake.ticks_ms(), sink)
    assert len(sink) == 2
    types = {sink.pop().event_type, sink.pop().event_type}
    assert types == {"fast", "slow"}


def test_handle_set_period_adds_heartbeat():
    """set_period() should add a heartbeat to a previously non-periodic handler."""
    fake = FakeTicks()
    dispatcher = SimpleEventDispatcher(ticks=fake)
    handle = dispatcher.register("tick", lambda e: None)

    assert handle.period_ms is None

    handle.set_period(300)
    assert handle.period_ms == 300


def test_handle_set_period_changes_heartbeat():
    """set_period() should replace the existing heartbeat."""
    fake = FakeTicks()
    dispatcher = SimpleEventDispatcher(ticks=fake)
    handle = dispatcher.register("tick", lambda e: None, period_ms=100)

    handle.set_period(500)
    assert handle.period_ms == 500


def test_handle_set_period_none_removes_heartbeat():
    """set_period(None) should remove the heartbeat."""
    fake = FakeTicks()
    dispatcher = SimpleEventDispatcher(ticks=fake)
    handle = dispatcher.register("tick", lambda e: None, period_ms=100)

    handle.set_period(None)
    assert handle.period_ms is None


def test_heartbeat_events_dispatch_through_runner():
    """ServiceRunner should poll heartbeats and dispatch their events."""
    fake = FakeTicks()
    received = []
    sink = EventQueueSink(max_size=8)
    dispatcher = SimpleEventDispatcher(ticks=fake)
    dispatcher.register("pulse", lambda e: received.append(e.event_type),
                        period_ms=100)
    runner = ServiceRunner([], sink, dispatcher, ticks=fake)

    # Not due yet.
    runner.service_once()
    assert received == []

    # Advance past the period and service again.
    fake.advance(100)
    runner.service_once()
    assert received == ["pulse"]


def test_heartbeat_and_component_events_both_dispatch():
    """Both component events and heartbeat events should dispatch in the same tick."""
    fake = FakeTicks()
    received = []

    class _Emitter:
        """Component that always emits."""

        def service(self, event_sink, now_ms):
            """Emit a component event."""
            event_sink.emit(self, "component.event")

    sink = EventQueueSink(max_size=8)
    dispatcher = SimpleEventDispatcher(ticks=fake)
    dispatcher.register("component.event",
                        lambda e: received.append("component"))
    dispatcher.register("heartbeat.event",
                        lambda e: received.append("heartbeat"),
                        period_ms=100)
    runner = ServiceRunner([_Emitter()], sink, dispatcher, ticks=fake)

    fake.advance(100)
    runner.service_once()

    assert "component" in received
    assert "heartbeat" in received


# -- ServiceRunner --


class _StubService:
    """Minimal serviceable component for testing."""

    def __init__(self, event_type="stub.event"):
        """Create a stub that emits *event_type* on each service call."""
        self._event_type = event_type

    def service(self, event_sink, now_ms):
        """Emit one event per service call."""
        event_sink.emit(self, self._event_type)


def test_runner_services_and_dispatches():
    """ServiceRunner should service all components, then dispatch events."""
    fake = FakeTicks()
    received = []
    svc = _StubService("test.ping")
    sink = EventQueueSink(max_size=4)
    dispatcher = SimpleEventDispatcher()
    dispatcher.register("test.ping", lambda e: received.append(e.event_type))

    runner = ServiceRunner([svc], sink, dispatcher, ticks=fake)
    runner.service_once()

    assert received == ["test.ping"]
    assert not sink.has_events()


def test_runner_handles_multiple_services():
    """ServiceRunner should handle multiple services in one pass."""
    fake = FakeTicks()
    received = []
    svc_a = _StubService("a")
    svc_b = _StubService("b")
    sink = EventQueueSink(max_size=8)
    dispatcher = SimpleEventDispatcher()
    dispatcher.register("a", lambda e: received.append("a"))
    dispatcher.register("b", lambda e: received.append("b"))

    runner = ServiceRunner([svc_a, svc_b], sink, dispatcher, ticks=fake)
    runner.service_once()

    assert received == ["a", "b"]


def test_runner_handles_no_events():
    """ServiceRunner should handle a pass where no events are emitted."""

    class _QuietService:
        """Service that emits nothing."""

        def service(self, event_sink, now_ms):
            """Do nothing."""

    fake = FakeTicks()
    sink = EventQueueSink(max_size=4)
    dispatcher = SimpleEventDispatcher()
    runner = ServiceRunner([_QuietService()], sink, dispatcher, ticks=fake)
    runner.service_once()  # should not raise

    assert not sink.has_events()


def test_runner_returns_shared_timestamp():
    """service_once() should return the captured now_ms."""
    fake = FakeTicks()
    sink = EventQueueSink(max_size=4)
    dispatcher = SimpleEventDispatcher()
    runner = ServiceRunner([], sink, dispatcher, ticks=fake)

    fake.advance(42)
    assert runner.service_once() == 42


def test_runner_passes_same_timestamp_to_all():
    """All components should receive the same now_ms on a single service_once() call."""
    fake = FakeTicks()
    timestamps = []

    class _Recorder:
        """Record each now_ms received."""

        def service(self, event_sink, now_ms):
            """Append now_ms to the shared list."""
            timestamps.append(now_ms)

    sink = EventQueueSink(max_size=4)
    dispatcher = SimpleEventDispatcher()
    runner = ServiceRunner(
        [_Recorder(), _Recorder(), _Recorder()], sink, dispatcher, ticks=fake
    )

    fake.advance(77)
    runner.service_once()

    assert timestamps == [77, 77, 77]


def test_runner_defaults_to_real_ticks():
    """ServiceRunner with no ticks argument should use chumicro_timing.ticks_ms."""
    sink = EventQueueSink(max_size=4)
    dispatcher = SimpleEventDispatcher()
    runner = ServiceRunner([], sink, dispatcher)

    now = runner.service_once()

    assert isinstance(now, int)
    assert now >= 0


# -- FakeEventSink --


def test_fake_sink_records_events():
    """FakeEventSink should record all emitted events in a list."""
    sink = FakeEventSink()
    sink.emit("src", "tick", data=1)
    sink.emit("src", "tick", data=2)

    assert len(sink) == 2
    assert sink.events[0].data == 1
    assert sink.events[1].data == 2


def test_fake_sink_pop():
    """FakeEventSink.pop should return events in FIFO order."""
    sink = FakeEventSink()
    sink.emit("s", "t1")
    sink.emit("s", "t2")

    assert sink.pop().event_type == "t1"
    assert sink.pop().event_type == "t2"
    assert sink.pop() is None


def test_fake_sink_clear():
    """FakeEventSink.clear should discard all recorded events."""
    sink = FakeEventSink()
    sink.emit("s", "t")
    sink.clear()

    assert len(sink) == 0
    assert not sink.has_events()
