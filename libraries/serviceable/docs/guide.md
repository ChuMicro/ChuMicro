# User Guide

## Overview

`chumicro-serviceable` provides a standard pattern for active components in the Chumicro ecosystem.  Instead of each library inventing its own `poll()` / callback / `next_event()` API, every active component implements a single method:

```python
def service(self, event_sink):
    """Do one tick of work; emit zero or more events."""
```

A shared `ServiceRunner` calls `service()` on each component, drains the event sink, and dispatches events to registered handlers.  This replaces ad-hoc drain loops in user code.

## The pattern

1. **Components** implement `service(event_sink)` — they do one tick of work and emit events into the sink.
2. **EventQueueSink** is a fixed-capacity ring buffer that collects events.
3. **SimpleEventDispatcher** routes events to handler functions by event type.
4. **ServiceRunner** ties it together: service → drain → dispatch.

## Getting started

```python
from chumicro_serviceable import EventQueueSink, ServiceRunner, SimpleEventDispatcher
from chumicro_timing import Heartbeat

# Create components
heartbeat = Heartbeat(period_ms=1000, event_type=Heartbeat.EVENT_TICK)

# Create the event infrastructure
sink = EventQueueSink(max_size=16)
dispatcher = SimpleEventDispatcher()

# Register handlers
dispatcher.register(Heartbeat.EVENT_TICK, lambda e: print("beat!"))

# Wire everything together
runner = ServiceRunner([heartbeat], sink, dispatcher)

# Main loop
while True:
    runner.service_once()
```

## Multiple components

The pattern scales to many components with no extra boilerplate:

```python
runner = ServiceRunner(
    services=[heartbeat, mqtt_client, button_scanner],
    event_sink=EventQueueSink(max_size=32),
    dispatcher=dispatcher,
)

while True:
    runner.service_once()
```

## Using the sink directly

You don't need `ServiceRunner` if you prefer manual control:

```python
sink = EventQueueSink(max_size=8)

heartbeat.service(sink)

while sink.has_events():
    event = sink.pop()
    print(f"Got {event.event_type} from {event.source}")
```

## Memory notes

- `EventQueueSink` pre-allocates its backing deque at construction time — no resizing during operation.
- `Event` uses `__slots__` to minimise per-instance memory.
- Individual `Event` objects are created on each `emit()`.  If GC pressure becomes measurable on your board, the sink capacity can be tuned via `max_size`.

## Writing your own serviceable component

Any object with a `service(event_sink)` method works with `ServiceRunner`.  No base class or import from `chumicro-serviceable` is required — the contract is duck-typed:

```python
class TemperatureMonitor:
    EVENT_HIGH = "temp.high"

    def __init__(self, sensor, threshold):
        self._sensor = sensor
        self._threshold = threshold

    def service(self, event_sink):
        reading = self._sensor.read()
        if reading > self._threshold:
            event_sink.emit(self, self.EVENT_HIGH, reading)
```

Wire it into a runner alongside other components:

```python
runner = ServiceRunner(
    services=[heartbeat, temp_monitor],
    event_sink=EventQueueSink(max_size=16),
    dispatcher=dispatcher,
)
```

The `event_sink.emit()` signature is `emit(source, event_type, data=None)` — it returns `True` on success and `False` if the sink is full.

## Testing serviceable components

The `chumicro_serviceable.testing` module provides `FakeEventSink` — a list-backed sink with no capacity limit, designed for assertions in host-side tests:

```python
from chumicro_serviceable.testing import FakeEventSink

sink = FakeEventSink()
component.service(sink)

assert len(sink.events) == 1
assert sink.events[0].event_type == "heartbeat.tick"
```

See the [testing helpers](testing.md) page for detailed usage.

## Platform notes

All classes use only basic Python features and work identically on CPython, MicroPython, and CircuitPython.  No `abc`, `typing`, or `asyncio` dependencies.
