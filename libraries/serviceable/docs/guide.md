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
heartbeat = Heartbeat(period_ms=1000)

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

- `EventQueueSink` pre-allocates its backing list at construction time — no list resizing during operation.
- `Event` uses `__slots__` to minimise per-instance memory.
- Individual `Event` objects are created on each `emit()`.  If GC pressure becomes measurable on your board, the sink capacity can be tuned via `max_size`.

## Platform notes

All classes use only basic Python features and work identically on CPython, MicroPython, and CircuitPython.  No `abc`, `typing`, or `asyncio` dependencies.
