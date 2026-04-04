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
4. **ServiceRunner** ties it together: capture time → service → poll heartbeats → drain → dispatch.

## Getting started

The simplest way to use the dispatcher is with a heartbeat-integrated handler — no component class required:

```python
from chumicro_serviceable import EventQueueSink, ServiceRunner, SimpleEventDispatcher

sink = EventQueueSink(max_size=16)
dispatcher = SimpleEventDispatcher()

dispatcher.register("led.blink", lambda e: toggle_led(), period_ms=500)

runner = ServiceRunner([], sink, dispatcher)

while True:
    runner.service_once()
```

For components with their own state or logic, implement the `service()` contract:

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

## Handler handles

`register()` returns a `HandlerHandle` — a lightweight object for inspecting and mutating the registration at runtime:

```python
handle = dispatcher.register("led.blink", blink_handler, period_ms=500)

# Inspect the registration.
print(handle.event_type)   # "led.blink"
print(handle.period_ms)    # 500
print(handle.priority)     # PRIORITY_NORMAL (2)
print(handle.active)       # True

# Change the blink rate.
handle.set_period(100)

# Change the priority.
handle.set_priority(PRIORITY_HIGH)

# Stop the handler entirely.
handle.unregister()
print(handle.active)       # False
```

The old `dispatcher.unregister(event_type)` method still works for convenience.

## Heartbeat-integrated handlers

For simple periodic callbacks, pass `period_ms` to `register()`:

```python
dispatcher.register("sensor.read", read_sensor, period_ms=5000)
dispatcher.register("heartbeat.tick", log_alive, period_ms=60000)
```

The `ServiceRunner` calls `poll_heartbeats()` on the dispatcher each tick.  When the heartbeat period elapses, the dispatcher emits an event into the sink that flows through the normal dispatch path.  This eliminates the need for a dedicated component class when all you want is a periodic callback.

You can change or remove the heartbeat at runtime via the handle:

```python
handle = dispatcher.register("led.blink", blink, period_ms=500)

# Speed up.
handle.set_period(100)

# Convert to a one-shot handler (remove the heartbeat).
handle.set_period(None)
```

## Priority levels

Four priority constants are available: `PRIORITY_CRITICAL` (0), `PRIORITY_HIGH` (1), `PRIORITY_NORMAL` (2, default), `PRIORITY_LOW` (3).

```python
from chumicro_serviceable import PRIORITY_HIGH

dispatcher.register("alarm", alarm_handler, priority=PRIORITY_HIGH)
```

Priority levels are stored on the handler entry and can be changed at runtime via `handle.set_priority()`.  Priority-based dispatch ordering is planned for a future release (Phase 3 of Decision 0018).

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
- `_HandlerEntry` and `HandlerHandle` use `__slots__` to minimise per-instance memory.
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
