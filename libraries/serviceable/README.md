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
| `SimpleEventDispatcher()` | Routes events to handler functions by event type |
| `SimpleEventDispatcher.register(event_type, handler)` | Register a handler for an event type |
| `SimpleEventDispatcher.unregister(event_type)` | Remove a handler |
| `SimpleEventDispatcher.dispatch(event)` | Route an event to its handler |
| `ServiceRunner(services, event_sink, dispatcher, ticks=None)` | Service → drain → dispatch loop with shared timestamps |
| `ServiceRunner.service_once()` | Capture time, service all components, drain and dispatch; returns `now_ms` |

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
- Individual `Event` objects are created per `emit()`.  Tune `max_size` if GC pressure is measurable on your board.

## Docs

- [User guide](docs/guide.md) — the pattern, getting started, writing components
- [API reference](docs/api.md) — full API documentation
- [Testing helpers](docs/testing.md) — using `FakeEventSink` in your tests
