# User Guide

## Overview

`chumicro-timing` provides two things:

1. **Tick helpers** — `ticks_ms()`, `ticks_diff()`, and `ticks_add()` that handle counter wraparound correctly across all three Python runtimes.
2. **Heartbeat** — a periodic timer that tells you when a time interval has elapsed, without blocking.

These are the building blocks for non-blocking timing on microcontrollers. Instead of calling `time.sleep()` (which blocks everything), you check `heartbeat.poll()` on each pass through your main loop.

## Getting started

### Basic heartbeat

The most common pattern is a periodic action in a main loop:

```python
from chumicro_timing import Heartbeat

led_heartbeat = Heartbeat(period_ms=500)

while True:
    if led_heartbeat.poll():
        # This runs twice per second
        toggle_led()
```

`poll()` returns `True` once per elapsed period and advances the internal timer. Calling it again immediately returns `False` until the next period elapses.

### Multiple timers

You can run several heartbeats at different rates:

```python
from chumicro_timing import Heartbeat

fast = Heartbeat(period_ms=100)   # 10 Hz
slow = Heartbeat(period_ms=5000)  # every 5 seconds

while True:
    if fast.poll():
        read_sensor()
    if slow.poll():
        send_report()
```

### Checking without consuming

`is_due()` tells you whether the period has elapsed without advancing the timer. This is useful when you need to check timing state without committing to an action:

```python
if heartbeat.is_due():
    # Period has elapsed, but the timer hasn't been reset yet.
    # Calling is_due() again will still return True.
    pass
```

Call `poll()` when you're ready to consume the beat and start the next period.

### Resetting

`reset()` restarts the timer from the current moment:

```python
heartbeat.reset()
# The next beat is now period_ms from right now,
# regardless of when the last beat was.
```

## Using ticks directly

For custom timing logic that doesn't fit the heartbeat pattern, use the tick functions directly:

```python
from chumicro_timing import ticks_ms, ticks_diff, ticks_add

# Record a timestamp
start = ticks_ms()

# ... do work ...

# Check elapsed time (handles wraparound correctly)
elapsed = ticks_diff(ticks_ms(), start)

# Compute a deadline
deadline = ticks_add(start, 3000)  # 3 seconds from start
```

**Important**: Do not use plain subtraction (`end - start`) on tick values. The counter wraps every ~6.2 days, and plain subtraction gives wrong results near the boundary. Always use `ticks_diff()`.

## Wraparound details

The tick counter uses a 2²⁹ ms period (~6.2 days). This keeps all arithmetic within small integers, avoiding heap-allocated big integers on boards without big-int support.

`ticks_diff()` is correct as long as the two timestamps are no more than ~3.1 days apart (half the period). For any practical embedded timing, this is more than sufficient.

`ticks_add()` rejects deltas at or beyond the half-period (±2²⁸ ms) with an `OverflowError`.

## Platform behavior

The tick source is selected automatically at import time:

| Priority | Source | Runtime |
|---|---|---|
| 1 | `supervisor.ticks_ms` | CircuitPython 7+ |
| 2 | `time.ticks_ms` | MicroPython, some CircuitPython builds |
| 3 | `time.monotonic_ns` | CPython, some CircuitPython boards |
| 4 | `time.monotonic` | Final fallback (float seconds → int ms) |

All sources are masked to the 2²⁹ period, so behavior is identical regardless of which source is used.

## Serviceable pattern

The `poll()` API works well when one piece of code owns the heartbeat and acts on it directly.  But as applications grow, you often want to **decouple the thing that produces timing events from the thing that handles them**.  That's what the serviceable pattern from `chumicro-serviceable` is for.

The core idea is **indirection**: instead of checking `poll()` and calling a handler inline, the heartbeat emits an event into a shared sink, and a dispatcher routes it to the right handler later.  This means:

- Components don't need to know about each other — the heartbeat doesn't call your handler directly.
- You can wire multiple independent components (heartbeats, sensors, network handlers) into a single dispatch loop.
- Adding or removing a handler doesn't require changing the component that emits the event.

To use the serviceable pattern, pass an `event_type` string to the constructor.  Each heartbeat should have a distinct event type so the dispatcher can route events correctly:

```python
from chumicro_serviceable import EventQueueSink, ServiceRunner, SimpleEventDispatcher
from chumicro_timing import Heartbeat

led_beat = Heartbeat(period_ms=500, event_type="led.blink")
sensor_beat = Heartbeat(period_ms=5000, event_type="sensor.read")

sink = EventQueueSink(max_size=8)
dispatcher = SimpleEventDispatcher()
dispatcher.register("led.blink", lambda e: print("blink!"))
dispatcher.register("sensor.read", lambda e: print("reading sensor"))

runner = ServiceRunner([led_beat, sensor_beat], sink, dispatcher)

while True:
    runner.service_once()
```

When a beat is due, `service()` emits the configured event type into the sink.  Calling `service()` without an `event_type` raises `RuntimeError` — this prevents accidental use without explicit routing.

For simple cases where one piece of code owns the heartbeat, `poll()` is still the right choice.  Reach for the serviceable pattern when you need the decoupling.

## Integration with a tick-based scheduler

`Heartbeat` is designed to be polled from a main loop or tick-based scheduler — it never blocks. A typical pattern:

```python
from chumicro_timing import Heartbeat

heartbeat = Heartbeat(period_ms=1000)

def on_tick():
    """Called once per scheduler tick."""
    if heartbeat.poll():
        do_periodic_work()
```

See the [examples](../examples/) directory for complete runnable scripts.

