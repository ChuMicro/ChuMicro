"""Core serviceable-pattern abstractions for the Chumicro ecosystem.

Provides a standard way for active components to emit events into a shared
sink, and for application code to dispatch those events to handlers.

The pattern:

1. Components implement ``service(event_sink)`` — do one tick of work,
   emit zero or more events.
2. A ``ServiceRunner`` calls ``service()`` on each component, then drains
   the sink and dispatches events.
3. User code registers handlers via ``SimpleEventDispatcher``.

All classes are cross-runtime compatible (CPython, MicroPython, CircuitPython).
"""


class Event:
    """A single occurrence emitted by a serviceable component.

    Attributes:
        source: The object that emitted the event.
        event_type: A string or constant identifying what happened.
        data: Optional payload (default ``None``).
    """

    __slots__ = ("source", "event_type", "data")

    def __init__(self, source, event_type, data=None):
        """Create an event."""
        self.source = source
        self.event_type = event_type
        self.data = data

    def __repr__(self):
        """Return a developer-friendly representation."""
        return f"Event({self.event_type!r}, source={self.source!r}, data={self.data!r})"


class EventQueueSink:
    """Fixed-capacity ring buffer that receives events from serviceable components.

    The backing list is pre-allocated at init time to avoid resizing.
    Individual ``Event`` objects are created on each ``emit()`` call;
    they use ``__slots__`` to minimise per-instance memory.

    Args:
        max_size: Maximum number of events the buffer can hold.
    """

    def __init__(self, max_size=16):
        """Create a sink with room for *max_size* events."""
        self._items = [None] * max_size
        self._head = 0
        self._tail = 0
        self._count = 0

    def emit(self, source, event_type, data=None):
        """Record an event.  Returns ``False`` if the buffer is full."""
        if self._count >= len(self._items):
            return False
        self._items[self._tail] = Event(source, event_type, data)
        self._tail = (self._tail + 1) % len(self._items)
        self._count += 1
        return True

    def has_events(self):
        """Return whether there are unread events in the buffer."""
        return self._count > 0

    def pop(self):
        """Remove and return the oldest event, or ``None`` if empty."""
        if self._count == 0:
            return None
        event = self._items[self._head]
        self._items[self._head] = None
        self._head = (self._head + 1) % len(self._items)
        self._count -= 1
        return event

    def clear(self):
        """Discard all pending events and reset the buffer."""
        for i in range(len(self._items)):
            self._items[i] = None
        self._head = 0
        self._tail = 0
        self._count = 0

    def __len__(self):
        """Return the number of pending events."""
        return self._count


class SimpleEventDispatcher:
    """Route events to registered handler functions by event type.

    Handlers are registered as ``(event_type, callable)`` pairs.
    When ``dispatch(event)`` is called, the handler matching
    ``event.event_type`` is invoked with the event as its sole argument.
    Unmatched events are silently ignored.
    """

    def __init__(self):
        """Create a dispatcher with no registered handlers."""
        self._handlers = {}

    def register(self, event_type, handler):
        """Register *handler* to be called for events of *event_type*."""
        self._handlers[event_type] = handler

    def unregister(self, event_type):
        """Remove the handler for *event_type*, if any."""
        self._handlers.pop(event_type, None)

    def dispatch(self, event):
        """Route *event* to its registered handler, if one exists."""
        handler = self._handlers.get(event.event_type)
        if handler is not None:
            handler(event)


class ServiceRunner:
    """Run serviceable components and dispatch their events.

    This replaces ad-hoc drain loops in user code with a single
    standard call::

        runner = ServiceRunner(services, sink, dispatcher)
        # In your main loop:
        runner.service_once()

    Args:
        services: Iterable of objects that implement ``service(event_sink)``.
        event_sink: An ``EventQueueSink`` (or duck-typed equivalent).
        dispatcher: A ``SimpleEventDispatcher`` (or duck-typed equivalent).
    """

    def __init__(self, services, event_sink, dispatcher):
        """Create a runner wiring *services* → *event_sink* → *dispatcher*."""
        self._services = services
        self._event_sink = event_sink
        self._dispatcher = dispatcher

    def service_once(self):
        """Service all components once, then drain and dispatch events."""
        for svc in self._services:
            svc.service(self._event_sink)

        while self._event_sink.has_events():
            event = self._event_sink.pop()
            self._dispatcher.dispatch(event)

