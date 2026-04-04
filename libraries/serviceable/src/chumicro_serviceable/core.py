"""Core serviceable-pattern abstractions for the Chumicro ecosystem.

Provides a standard way for active components to emit events into a shared
sink, and for application code to dispatch those events to handlers.

The pattern:

1. Components implement ``service(event_sink, now_ms)`` — do one tick of work,
   emit zero or more events.
2. A ``ServiceRunner`` captures time once, calls ``service()`` on each
   component with a shared timestamp, then drains the sink and dispatches
   events.
3. User code registers handlers via ``SimpleEventDispatcher``.

All classes are cross-runtime compatible (CPython, MicroPython, CircuitPython).
"""

from collections import deque


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

    Backed by ``collections.deque`` which is implemented in C on
    MicroPython and CircuitPython, giving O(1) append/popleft with
    pre-allocated storage and no Python-level index bookkeeping.

    Individual ``Event`` objects are created on each ``emit()`` call;
    they use ``__slots__`` to minimise per-instance memory.

    Args:
        max_size: Maximum number of events the buffer can hold.
    """

    def __init__(self, max_size=16):
        """Create a sink with room for *max_size* events."""
        self._max_size = max_size
        try:
            # MicroPython/CircuitPython: third arg is flags;
            # 1 = FLAG_CHECK_OVERFLOW (raises IndexError on append when full).
            self._items = deque((), max_size, 1)
        except TypeError:
            # CPython: no flags argument.
            self._items = deque((), max_size)

    def emit(self, source, event_type, data=None):
        """Record an event.  Returns ``False`` if the buffer is full."""
        if len(self._items) >= self._max_size:
            return False
        self._items.append(Event(source, event_type, data))
        return True

    def has_events(self):
        """Return whether there are unread events in the buffer."""
        return bool(self._items)

    def pop(self):
        """Remove and return the oldest event, or ``None`` if empty."""
        if not self._items:
            return None
        return self._items.popleft()

    def clear(self):
        """Discard all pending events and reset the buffer."""
        while self._items:
            self._items.popleft()

    def __len__(self):
        """Return the number of pending events."""
        return len(self._items)


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

    Captures ``ticks_ms()`` once per ``service_once()`` call and passes
    the shared timestamp to every component, ensuring all components
    see the same moment in time.

    This replaces ad-hoc drain loops in user code with a single
    standard call::

        runner = ServiceRunner(services, sink, dispatcher)
        # In your main loop:
        now = runner.service_once()

    Args:
        services: Iterable of objects that implement ``service(event_sink, now_ms)``.
        event_sink: An ``EventQueueSink`` (or duck-typed equivalent).
        dispatcher: A ``SimpleEventDispatcher`` (or duck-typed equivalent).
        ticks: Optional tick source (must have a ``ticks_ms`` method).
            Defaults to ``chumicro_timing.ticks_ms``.
    """

    def __init__(self, services, event_sink, dispatcher, ticks=None):
        """Create a runner wiring *services* → *event_sink* → *dispatcher*."""
        self._services = services
        self._event_sink = event_sink
        self._dispatcher = dispatcher
        if ticks is not None:
            self._ticks_ms = ticks.ticks_ms
        else:
            from chumicro_timing import ticks_ms

            self._ticks_ms = ticks_ms

    def service_once(self):
        """Capture time, service all components, then drain and dispatch events.

        Returns:
            The ``now_ms`` value passed to all components this tick.
        """
        now_ms = self._ticks_ms()
        for svc in self._services:
            svc.service(self._event_sink, now_ms)

        while self._event_sink.has_events():
            event = self._event_sink.pop()
            self._dispatcher.dispatch(event)

        return now_ms
