"""Core serviceable-pattern abstractions for the Chumicro ecosystem.

Provides three ways to register work with a ``ServiceRunner``:

1. **Gate-based** — ``add(service, handler=fn)``: the runner calls
   ``service.service(now_ms)``; if it returns ``True``, the handler is
   queued and fired in batch after all services are checked.
2. **Event-based** — ``add(service)``: the runner calls
   ``service.service(event_sink, now_ms)``; emitted events are drained
   and dispatched after the handler batch.
3. **Periodic** — ``add_periodic(handler, period_ms)``: the handler fires
   every *period_ms* milliseconds with no service object.

All classes are cross-runtime compatible (CPython, MicroPython, CircuitPython).
"""

from collections import deque

try:
    from micropython import const
except ImportError:

    def const(x):
        """Identity fallback for CPython (no micropython.const)."""
        return x


# Priority constants — lower number = higher priority.
PRIORITY_CRITICAL = const(0)
PRIORITY_HIGH = const(1)
PRIORITY_NORMAL = const(2)
PRIORITY_LOW = const(3)


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


class _HandlerEntry:
    """Internal registration record for a handler in the dispatcher."""

    __slots__ = ("event_type", "handler", "priority", "active")

    def __init__(self, event_type, handler, priority):
        """Create a handler entry."""
        self.event_type = event_type
        self.handler = handler
        self.priority = priority
        self.active = True


class HandlerHandle:
    """Opaque handle returned by ``SimpleEventDispatcher.register()``.

    Provides runtime mutation of a registered handler: change its
    priority or unregister it entirely.

    Read-only properties expose the current state for inspection and
    testing.
    """

    __slots__ = ("_entry", "_dispatcher")

    def __init__(self, entry, dispatcher):
        """Create a handle wrapping *entry* owned by *dispatcher*."""
        self._entry = entry
        self._dispatcher = dispatcher

    @property
    def event_type(self):
        """Return the event type this handler is registered for."""
        return self._entry.event_type

    @property
    def priority(self):
        """Return the current priority level."""
        return self._entry.priority

    @property
    def active(self):
        """Return whether the handler is still registered."""
        return self._entry.active

    def set_priority(self, priority):
        """Change the priority level for this handler."""
        self._entry.priority = priority

    def unregister(self):
        """Remove this handler from the dispatcher."""
        self._dispatcher._remove_entry(self._entry)

    def __repr__(self):
        """Return a developer-friendly representation."""
        status = "active" if self._entry.active else "inactive"
        return f"HandlerHandle({self._entry.event_type!r}, {status})"


class SimpleEventDispatcher:
    """Route events to registered handler functions by event type.

    Handlers are registered as ``(event_type, callable)`` pairs via
    ``register()``, which returns a ``HandlerHandle`` for runtime mutation.
    When ``dispatch(event)`` is called, the handler matching
    ``event.event_type`` is invoked with the event as its sole argument.
    Unmatched events are silently ignored.

    Registration order determines execution order within equal priorities.
    Re-registering the same event type replaces the old entry.
    """

    def __init__(self):
        """Create a dispatcher with no registered handlers."""
        self._entries = []
        self._index = {}

    def register(self, event_type, handler, priority=PRIORITY_NORMAL):
        """Register *handler* to be called for events of *event_type*.

        Returns a ``HandlerHandle`` for runtime mutation.

        Args:
            event_type: The event type string to match.
            handler: Callable invoked with the ``Event`` as sole argument.
            priority: Priority level (default ``PRIORITY_NORMAL``).
        """
        # Replace existing entry for the same event_type.
        old = self._index.pop(event_type, None)
        if old is not None:
            old.active = False
            self._entries.remove(old)

        entry = _HandlerEntry(event_type, handler, priority)
        self._entries.append(entry)
        self._index[event_type] = entry
        return HandlerHandle(entry, self)

    def unregister(self, event_type):
        """Remove the handler for *event_type*, if any."""
        entry = self._index.pop(event_type, None)
        if entry is not None:
            entry.active = False
            self._entries.remove(entry)

    def dispatch(self, event):
        """Route *event* to its registered handler, if one exists."""
        entry = self._index.get(event.event_type)
        if entry is not None and entry.active:
            entry.handler(event)

    def _remove_entry(self, entry):
        """Remove *entry* from the dispatcher (called by ``HandlerHandle``)."""
        if entry.event_type in self._index and self._index[entry.event_type] is entry:
            del self._index[entry.event_type]
        entry.active = False
        try:
            self._entries.remove(entry)
        except ValueError:
            pass


class _ServiceEntry:
    """Internal record for a service registered with the runner."""

    __slots__ = ("service", "handler", "heartbeat", "active")

    def __init__(self, service, handler, heartbeat):
        """Create a service entry."""
        self.service = service
        self.handler = handler
        self.heartbeat = heartbeat
        self.active = True


class ServiceHandle:
    """Opaque handle returned by ``ServiceRunner.add()`` or ``add_periodic()``.

    Provides runtime mutation of a registered service: change its period
    or remove it from the runner entirely.

    Read-only properties expose the current state for inspection and
    testing.
    """

    __slots__ = ("_entry", "_runner")

    def __init__(self, entry, runner):
        """Create a handle wrapping *entry* owned by *runner*."""
        self._entry = entry
        self._runner = runner

    @property
    def period_ms(self):
        """Return the service period in milliseconds, or ``None``."""
        if self._entry.heartbeat is None:
            return None
        return self._entry.heartbeat.period_ms

    @property
    def active(self):
        """Return whether the service is still registered."""
        return self._entry.active

    def set_period(self, period_ms):
        """Add, change, or remove the period for this service.

        Pass ``None`` to remove an existing period (service runs every tick).
        A non-None value creates a new ``Heartbeat`` (resetting the timer).
        """
        if period_ms is None:
            self._entry.heartbeat = None
            return
        from chumicro_timing import Heartbeat

        self._entry.heartbeat = Heartbeat(
            period_ms, ticks=self._runner._ticks
        )

    def remove(self):
        """Remove this service from the runner."""
        self._runner._remove_entry(self._entry)

    def __repr__(self):
        """Return a developer-friendly representation."""
        status = "active" if self._entry.active else "removed"
        hb = self._entry.heartbeat
        period = hb.period_ms if hb is not None else None
        return f"ServiceHandle(period_ms={period}, {status})"


class ServiceRunner:
    """Run serviceable components and dispatch their events.

    Captures ``ticks_ms()`` once per ``service_once()`` call and passes
    the shared timestamp to every due component, ensuring all components
    see the same moment in time.

    Three registration paths:

    - ``add(service, handler=fn)`` — **gate-based**: calls
      ``service.service(now_ms)``; if ``True``, queues ``handler(now_ms)``.
    - ``add(service)`` — **event-based**: calls
      ``service.service(event_sink, now_ms)``; events are drained and
      dispatched after the handler batch.
    - ``add_periodic(handler, period_ms)`` — **periodic**: fires
      ``handler(now_ms)`` every *period_ms* milliseconds.

    ``service_once()`` processes services in three phases:

    1. Check all services (period gate → service gate) and collect
       due handlers.
    2. Batch-fire all gate and periodic handlers.
    3. Drain the event sink and dispatch events.

    Args:
        event_sink: Optional ``EventQueueSink`` for event-based services.
        dispatcher: Optional ``SimpleEventDispatcher`` for event-based services.
        ticks: Optional tick source (must have a ``ticks_ms`` method).
            Defaults to ``chumicro_timing.ticks_ms``.
    """

    def __init__(self, event_sink=None, dispatcher=None, ticks=None):
        """Create a runner.  Provide *event_sink* and *dispatcher* for event-based services."""
        self._entries = []
        self._pending = []
        self._event_sink = event_sink
        self._dispatcher = dispatcher
        self._ticks = ticks
        if ticks is not None:
            self._ticks_ms = ticks.ticks_ms
        else:
            from chumicro_timing import ticks_ms

            self._ticks_ms = ticks_ms

    def add(self, service, handler=None, period_ms=None):
        """Register a service to be called on each ``service_once()`` tick.

        **Gate-based** (handler provided): ``service.service(now_ms)``
        is called; if it returns ``True``, ``handler(now_ms)`` is queued
        and fired in batch after all services are checked.

        **Event-based** (no handler): ``service.service(event_sink, now_ms)``
        is called; emitted events are drained and dispatched.

        If *period_ms* is provided, the service is only checked when the
        period elapses.  Otherwise, it is checked every tick.

        Returns a ``ServiceHandle`` for runtime mutation.

        Args:
            service: Gate-based: object with ``service(now_ms) -> bool``.
                Event-based: object with ``service(event_sink, now_ms)``.
            handler: Optional callable ``handler(now_ms)`` for gate-based mode.
            period_ms: Optional interval in milliseconds.
        """
        heartbeat = None
        if period_ms is not None:
            from chumicro_timing import Heartbeat

            heartbeat = Heartbeat(period_ms, ticks=self._ticks)
        entry = _ServiceEntry(service, handler, heartbeat)
        self._entries.append(entry)
        return ServiceHandle(entry, self)

    def add_periodic(self, handler, period_ms):
        """Register a periodic handler with no service object.

        ``handler(now_ms)`` is called every *period_ms* milliseconds.
        Returns a ``ServiceHandle`` for runtime mutation.

        Args:
            handler: Callable ``handler(now_ms)`` to fire periodically.
            period_ms: Interval in milliseconds (required).
        """
        from chumicro_timing import Heartbeat

        heartbeat = Heartbeat(period_ms, ticks=self._ticks)
        entry = _ServiceEntry(None, handler, heartbeat)
        self._entries.append(entry)
        return ServiceHandle(entry, self)

    def service_once(self):
        """Capture time, service due components, then batch-fire handlers and dispatch.

        Processing order:

        1. Check each service entry (period gate, then service gate).
           Collect handlers that should fire.
        2. Batch-fire all gate-based and periodic handlers.
        3. Drain the event sink and dispatch events (if configured).

        Returns:
            The ``now_ms`` value used this tick.
        """
        now_ms = self._ticks_ms()
        pending = self._pending

        for entry in self._entries:
            if not entry.active:
                continue
            if entry.heartbeat is not None:
                if not entry.heartbeat.poll(now_ms):
                    continue

            if entry.handler is not None:
                if entry.service is not None:
                    # Gate-based: service returns True/False.
                    if entry.service.service(now_ms):
                        pending.append(entry.handler)
                else:
                    # Periodic: always fire.
                    pending.append(entry.handler)
            elif entry.service is not None:
                # Event-based: call service with event_sink.
                entry.service.service(self._event_sink, now_ms)

        # Batch-fire gate and periodic handlers.
        for handler in pending:
            handler(now_ms)
        pending.clear()

        # Drain event sink → dispatch.
        if self._event_sink is not None and self._dispatcher is not None:
            while self._event_sink.has_events():
                event = self._event_sink.pop()
                self._dispatcher.dispatch(event)

        return now_ms

    def _remove_entry(self, entry):
        """Remove *entry* from the runner (called by ``ServiceHandle``)."""
        entry.active = False
        try:
            self._entries.remove(entry)
        except ValueError:
            pass

