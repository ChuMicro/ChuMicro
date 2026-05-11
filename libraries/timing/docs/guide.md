# User Guide

## Overview

`chumicro-timing` provides two things:

1. **Tick helpers** — `ticks_ms()`, `ticks_diff()`, and `ticks_add()` that handle counter wraparound correctly across all three Python runtimes.
2. **Heartbeat** — a periodic timer that tells you when a time interval has elapsed, without blocking.

These are the building blocks for non-blocking timing on microcontrollers. Instead of calling `time.sleep()` (which blocks everything), you capture a timestamp once per loop and check `heartbeat.poll(now)` for each component.

## Getting started

### Basic heartbeat

The most common pattern is a periodic action in a main loop:

```python
from chumicro_timing import Heartbeat, ticks_ms

led_heartbeat = Heartbeat(period_ms=500)

while True:
    now = ticks_ms()
    if led_heartbeat.poll(now):
        # This runs twice per second
        toggle_led()
```

`poll(now_ms)` returns `True` once per elapsed period and advances the internal timer. Calling it again with the same timestamp returns `False` until the next period elapses.

### Shared timestamps

**Always capture `ticks_ms()` once per loop iteration** and pass the same value to every component. This prevents drift between independent clock reads:

```python
from chumicro_timing import Heartbeat, ticks_ms

fast = Heartbeat(period_ms=100)   # 10 Hz
slow = Heartbeat(period_ms=5000)  # every 5 seconds

while True:
    now = ticks_ms()  # ONE reading per iteration
    if fast.poll(now):
        read_sensor()
    if slow.poll(now):
        send_report()
```

On a slow microcontroller, calling `ticks_ms()` separately for each component would return slightly different values. A heartbeat that should fire at the same moment as another might not. Sharing the timestamp eliminates this class of bug.

### Checking without consuming

`is_due(now_ms)` tells you whether the period has elapsed without advancing the timer. This is useful when you need to check timing state without committing to an action:

```python
now = ticks_ms()
if heartbeat.is_due(now):
    # Period has elapsed, but the timer hasn't been reset yet.
    # Calling is_due(now) again will still return True.
    pass
```

Call `poll(now)` when you're ready to consume the beat and start the next period.

### Resetting

`reset(now_ms)` restarts the timer from the given timestamp:

```python
now = ticks_ms()
heartbeat.reset(now)
# The next beat is now period_ms from this moment,
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

## Platform notes

The tick source is selected automatically at import time:

| Priority | Source | Runtime |
|---|---|---|
| 1 | `supervisor.ticks_ms` | CircuitPython 7+ |
| 2 | `time.ticks_ms` | MicroPython, some CircuitPython builds |
| 3 | `time.monotonic_ns` | CPython, some CircuitPython boards |
| 4 | `time.monotonic` | Final fallback (float seconds → int ms) |

All sources are masked to the 2²⁹ period, so behavior is identical regardless of which source is used.

## Using with chumicro-runner

`Heartbeat` is designed to be polled from a main loop or tick-based scheduler — it never blocks. A typical pattern:

```python
from chumicro_timing import Heartbeat, ticks_ms

heartbeat = Heartbeat(period_ms=1000)

def on_tick() -> None:
    """Called once per scheduler tick."""
    now = ticks_ms()
    if heartbeat.poll(now):
        do_periodic_work()
```

For applications with many components, [`chumicro-runner`](https://chumicro.github.io/ChuMicro/runner/stable/) captures the timestamp once per tick and dispatches it to every registered service.

## Examples

The [examples](../examples/) directory contains complete runnable scripts:

| Example | What it shows |
|---|---|
| `heartbeat_blink.py` | Basic heartbeat in a main loop (the embedded hello world) |
| `multiple_heartbeats.py` | Several heartbeats at different rates sharing one timestamp |
| `timeout_check.py` | Using `ticks_diff()` for deadline-based timeout detection |
| `debounce.py` | Button debounce using `ticks_ms()` and `ticks_diff()` |
| `periodic_tick.py` | Manual periodic action — the same logic `Heartbeat` wraps |
| `circuitpython_blink.py` | LED blink on CircuitPython hardware |
| `circuitpython_debounce.py` | Button debounce on CircuitPython hardware |
| `micropython_blink.py` | LED blink on MicroPython hardware |
| `micropython_debounce.py` | Button debounce on MicroPython hardware |

Simulated examples run on CPython.  Hardware examples (`circuitpython_*` / `micropython_*`) require a real board — see the setup notes in each file.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) · [PyPI](https://pypi.org/project/chumicro-timing/) · [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
