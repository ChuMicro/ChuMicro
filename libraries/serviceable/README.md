# chumicro-serviceable

A standard service-and-event pattern for Chumicro libraries.

Components implement `service(event_sink, now_ms)` to do one tick of work and emit events.  A `ServiceRunner` captures time once, calls all components with a shared timestamp, and dispatches events to handlers — replacing ad-hoc polling and drain loops with a single standard contract.

## Installation

```bash
# CPython (pip)
pip install chumicro-serviceable

# CircuitPython (circup) — coming soon
# circup install chumicro-serviceable

# MicroPython (mip) — coming soon
# import mip; mip.install("chumicro-serviceable")
```

## Quick example

```python
from chumicro_serviceable import EventQueueSink, ServiceRunner, SimpleEventDispatcher

sink = EventQueueSink(max_size=16)
dispatcher = SimpleEventDispatcher()

# Heartbeat-integrated handler — no component class needed.
dispatcher.register("led.blink", lambda e: toggle_led(), period_ms=500)

runner = ServiceRunner([], sink, dispatcher)

while True:
    runner.service_once()
```

For components that need their own state or logic, implement `service(event_sink, now_ms)`:

```python
from chumicro_serviceable import EventQueueSink, ServiceRunner, SimpleEventDispatcher
from chumicro_timing import Heartbeat


class Blinker:
    EVENT_BLINK = "blinker.blink"

    def __init__(self, period_ms):
        self._heartbeat = Heartbeat(period_ms=period_ms)

    def service(self, event_sink, now_ms):
        if self._heartbeat.poll(now_ms):
            event_sink.emit(self, self.EVENT_BLINK)


blinker = Blinker(period_ms=1000)

sink = EventQueueSink(max_size=16)
dispatcher = SimpleEventDispatcher()
dispatcher.register(Blinker.EVENT_BLINK, lambda e: print("blink!"))

runner = ServiceRunner([blinker], sink, dispatcher)

while True:
    runner.service_once()
```

## What's included

### Core

| Symbol | Description |
|---|---|
| `Event(source, event_type, data=None)` | A single occurrence emitted by a component |
| `EventQueueSink(max_size=16)` | Fixed-capacity ring buffer backed by `collections.deque` |
| `EventQueueSink.emit(source, event_type, data=None)` | Record an event; returns `False` if full |
| `EventQueueSink.pop()` | Remove and return the oldest event, or `None` |
| `EventQueueSink.has_events()` | Check whether unread events exist |
| `EventQueueSink.clear()` | Discard all pending events |
| `SimpleEventDispatcher(ticks=None)` | Routes events to handler functions by event type |
| `SimpleEventDispatcher.register(event_type, handler, period_ms=None, priority=PRIORITY_NORMAL)` | Register a handler; returns a `HandlerHandle` |
| `SimpleEventDispatcher.unregister(event_type)` | Remove a handler by event type |
| `SimpleEventDispatcher.dispatch(event)` | Route an event to its handler |
| `SimpleEventDispatcher.poll_heartbeats(now_ms, event_sink)` | Emit events for any due heartbeat handlers |
| `HandlerHandle` | Opaque handle for runtime mutation of a registered handler |
| `HandlerHandle.set_period(period_ms)` | Add, change, or remove the heartbeat (`None` to remove) |
| `HandlerHandle.set_priority(priority)` | Change the priority level |
| `HandlerHandle.unregister()` | Remove this handler from the dispatcher |
| `HandlerHandle.event_type` | Read-only: the event type |
| `HandlerHandle.priority` | Read-only: the current priority |
| `HandlerHandle.period_ms` | Read-only: the heartbeat period, or `None` |
| `HandlerHandle.active` | Read-only: whether the handler is still registered |
| `ServiceRunner(services, event_sink, dispatcher, ticks=None)` | Service → drain → dispatch loop with shared timestamps |
| `ServiceRunner.service_once()` | Capture time, service all components, poll heartbeats, drain and dispatch; returns `now_ms` |

### Constants

| Symbol | Value | Description |
|---|---|---|
| `PRIORITY_CRITICAL` | 0 | Highest priority (Phase 3 dispatch ordering) |
| `PRIORITY_HIGH` | 1 | High priority |
| `PRIORITY_NORMAL` | 2 | Default priority |
| `PRIORITY_LOW` | 3 | Lowest priority |

### Testing

| Symbol | Description |
|---|---|
| `FakeEventSink()` | List-backed event sink for host-side tests (no capacity limit) |
| `FakeEventSink.events` | Direct access to the list of recorded `Event` objects |

## Writing your own serviceable component

Any object with a `service(event_sink, now_ms)` method works with `ServiceRunner`.  No base class or import from `chumicro-serviceable` is required — the contract is duck-typed:

```python
class ButtonScanner:
    EVENT_PRESS = "button.press"

    def __init__(self, pin):
        self._pin = pin
        self._was_pressed = False

    def service(self, event_sink, now_ms):
        pressed = self._pin.value
        if pressed and not self._was_pressed:
            event_sink.emit(self, self.EVENT_PRESS)
        self._was_pressed = pressed
```

The `now_ms` argument is a shared timestamp captured once per tick by the `ServiceRunner`.  Components that need timing (e.g., periodic heartbeats) use it; components that don't (e.g., button scanners) can ignore it.

## Heartbeat-integrated handlers

For simple periodic callbacks, you don't need a component class at all.  Pass `period_ms` to `register()` and the dispatcher handles the timing internally:

```python
dispatcher.register("sensor.read", read_sensor, period_ms=5000)
```

The `ServiceRunner` calls `poll_heartbeats()` each tick.  When the period elapses, the dispatcher emits an event that flows through the normal sink → dispatch path.

## Handler handles

`register()` returns a `HandlerHandle` for runtime mutation:

```python
handle = dispatcher.register("led.blink", blink_handler, period_ms=500)

# Change the blink rate at runtime.
handle.set_period(100)

# Stop blinking.
handle.unregister()
```

## Testing your components

The `chumicro_serviceable.testing` module provides `FakeEventSink` for verifying that components emit the right events:

```python
from chumicro_serviceable.testing import FakeEventSink

sink = FakeEventSink()
component.service(sink, 0)

assert len(sink.events) == 1
assert sink.events[0].event_type == "button.press"
```

## Platform support

All classes use only basic Python features and `collections.deque`.  Works identically on CPython, MicroPython, and CircuitPython.  Requires a full-build runtime with `deque` support (see [Decision 0015](../../plans/decisions/0015-board-architecture-support.md)).

## Memory notes

- `EventQueueSink` is backed by `collections.deque` (C-level on MicroPython/CircuitPython) with a fixed max size — no list resizing during operation.
- `Event` uses `__slots__` to minimise per-instance memory.
- `_HandlerEntry` and `HandlerHandle` use `__slots__` to minimise per-instance memory.
- Individual `Event` objects are created per `emit()`.  Tune `max_size` if GC pressure is measurable on your board.

## Docs

- [User guide](docs/guide.md) — the pattern, getting started, writing components
- [API reference](docs/api.md) — full API documentation
- [Testing helpers](docs/testing.md) — using `FakeEventSink` in your tests
