
"""Test helpers for libraries that depend on chumicro-serviceable.

Provides a ``FakeEventSink`` that records emitted events for assertion
in host-side tests, without the overhead of a ring buffer.

Usage::

    from chumicro_serviceable.testing import FakeEventSink

    sink = FakeEventSink()
    component.service(sink, 0)
    assert len(sink.events) == 1
    assert sink.events[0].event_type == "heartbeat.tick"
"""

from .core import Event


class FakeEventSink:
    """Simple list-backed event sink for tests.

    Every call to ``emit()`` appends an ``Event`` to ``self.events``.
    There is no capacity limit.
    """

    def __init__(self):
        """Create an empty fake sink."""
        self.events = []

    def emit(self, source, event_type, data=None):
        """Record an event.  Always returns ``True``."""
        self.events.append(Event(source, event_type, data))
        return True

    def has_events(self):
        """Return whether any events have been recorded."""
        return len(self.events) > 0

    def pop(self):
        """Remove and return the oldest event, or ``None`` if empty."""
        if not self.events:
            return None
        return self.events.pop(0)

    def clear(self):
        """Discard all recorded events."""
        self.events.clear()

    def __len__(self):
        """Return the number of recorded events."""
        return len(self.events)
