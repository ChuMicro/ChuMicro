"""Tests for the core serviceable-pattern abstractions.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via the lightweight test harness).
"""

from chumicro_serviceable import (
    Event,
    EventQueueSink,
    ServiceRunner,
    SimpleEventDispatcher,
)
from chumicro_serviceable.testing import FakeEventSink

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


# -- SimpleEventDispatcher --


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


# -- ServiceRunner --


class _StubService:
    """Minimal serviceable component for testing."""

    def __init__(self, event_type="stub.event"):
        self._event_type = event_type

    def service(self, event_sink):
        """Emit one event per service call."""
        event_sink.emit(self, self._event_type)


def test_runner_services_and_dispatches():
    """ServiceRunner should service all components, then dispatch events."""
    received = []
    svc = _StubService("test.ping")
    sink = EventQueueSink(max_size=4)
    dispatcher = SimpleEventDispatcher()
    dispatcher.register("test.ping", lambda e: received.append(e.event_type))

    runner = ServiceRunner([svc], sink, dispatcher)
    runner.service_once()

    assert received == ["test.ping"]
    assert not sink.has_events()


def test_runner_handles_multiple_services():
    """ServiceRunner should handle multiple services in one pass."""
    received = []
    svc_a = _StubService("a")
    svc_b = _StubService("b")
    sink = EventQueueSink(max_size=8)
    dispatcher = SimpleEventDispatcher()
    dispatcher.register("a", lambda e: received.append("a"))
    dispatcher.register("b", lambda e: received.append("b"))

    runner = ServiceRunner([svc_a, svc_b], sink, dispatcher)
    runner.service_once()

    assert received == ["a", "b"]


def test_runner_handles_no_events():
    """ServiceRunner should handle a pass where no events are emitted."""

    class _QuietService:
        def service(self, event_sink):
            pass

    sink = EventQueueSink(max_size=4)
    dispatcher = SimpleEventDispatcher()
    runner = ServiceRunner([_QuietService()], sink, dispatcher)
    runner.service_once()  # should not raise

    assert not sink.has_events()


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

