# User Guide

## Overview

`chumicro-serviceable` provides a standard pattern for active components in the Chumicro ecosystem.  Instead of each library inventing its own `poll()` / callback / `next_event()` API, every active component implements a single method:

```python
def service(self, event_sink, now_ms):
    """Do one tick of work; emit zero or more events."""
```

A shared `ServiceRunner` captures time once, calls `service()` on each component with the shared timestamp, drains the event sink, and dispatches events to registered handlers.  This replaces ad-hoc drain loops in user code.

## The pattern

1. **Components** implement `service(event_sink, now_ms)` — they do one tick of work and emit events into the sink.
2. **EventQueueSink** is a fixed-capacity ring buffer that collects events.
3. **SimpleEventDispatcher** routes events to handler functions by event type.
4. **ServiceRunner** ties it together: capture time → service → drain → dispatch.

## Getting started

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

## Shared timestamps

`ServiceRunner.service_once()` captures `ticks_ms()` once and passes the resulting timestamp to every component.  This ensures all components in the loop see the same moment in time, preventing drift between independent clock reads on slow microcontrollers.

The method returns `now_ms` so user code can use it for passive checks alongside the dispatch loop:

```python
while True:
    now = runner.service_once()
    if some_heartbeat.poll(now):
        do_something()
```

## Multiple components

The pattern scales to many components with no extra boilerplate:

```python
runner = ServiceRunner(
    services=[blinker, mqtt_client, button_scanner],
    event_sink=EventQueueSink(max_size=32),
    dispatcher=dispatcher,
)

while True:
    runner.service_once()
```

## Using the sink directly

You don't need `ServiceRunner` if you prefer manual control:

```python
from chumicro_timing import ticks_ms

sink = EventQueueSink(max_size=8)

now = ticks_ms()
component.service(sink, now)

while sink.has_events():
    event = sink.pop()
    print(f"Got {event.event_type} from {event.source}")
```

## Components that don't need time

Not every component cares about the shared timestamp.  The `now_ms` parameter is always provided, but components can ignore it:

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

## Components that use time

Components that need periodic timing can use `Heartbeat` with the shared `now_ms`:

```python
from chumicro_timing import Heartbeat


class TemperatureMonitor:
    EVENT_HIGH = "temp.high"

    def __init__(self, sensor, period_ms, threshold):
        self._sensor = sensor
        self._heartbeat = Heartbeat(period_ms=period_ms)
        self._threshold = threshold

    def service(self, event_sink, now_ms):
        if self._heartbeat.poll(now_ms):
            reading = self._sensor.read()
            if reading > self._threshold:
                event_sink.emit(self, self.EVENT_HIGH, reading)
```

## Memory notes

- `EventQueueSink` pre-allocates its backing deque at construction time — no resizing during operation.
- `Event` uses `__slots__` to minimise per-instance memory.
- Individual `Event` objects are created on each `emit()`.  If GC pressure becomes measurable on your board, the sink capacity can be tuned via `max_size`.

## Testing serviceable components

The `chumicro_serviceable.testing` module provides `FakeEventSink` — a list-backed sink with no capacity limit, designed for assertions in host-side tests:

```python
from chumicro_serviceable.testing import FakeEventSink

sink = FakeEventSink()
component.service(sink, 0)

assert len(sink.events) == 1
assert sink.events[0].event_type == "button.press"
```

See the [testing helpers](testing.md) page for detailed usage.

## Platform notes

All classes use only basic Python features and work identically on CPython, MicroPython, and CircuitPython.  No `abc`, `typing`, or `asyncio` dependencies.
