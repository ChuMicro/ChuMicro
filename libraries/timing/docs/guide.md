# User Guide

## Overview

`chumicro-timing` provides two things:

1. **Tick helpers** — `ticks_ms()`, `ticks_diff()`, and `ticks_add()` that handle counter wraparound correctly across all three Python runtimes.
2. **Value objects** built on those helpers:
    - `Deadline` — a single armed timeout: check `expired(now)` / `remaining(now)`, `reset(now)` to re-arm.
    - `Rate` — a drift-free periodic cadence (the replacement for the old `Heartbeat`): `due(now)` returns `True` at most once per period.

These are the building blocks for non-blocking timing on microcontrollers. Instead of calling `time.sleep()` (which blocks everything), you capture a timestamp once per loop and hand it to each timer.

For generator-based flows that suspend until a completion event, the opt-in `chumicro_timing.waits` submodule adds `Signal` and `wait_for` — the completion-wait vocabulary. Import it explicitly: `from chumicro_timing.waits import Signal, wait_for`.

## Getting started

### Basic periodic cadence

The most common pattern is a periodic action in a main loop:

```python
from chumicro_timing import Rate, ticks_ms

led_rate = Rate(500, ticks_ms())

while True:
    now = ticks_ms()
    if led_rate.due(now):
        # This runs twice per second
        toggle_led()
```

`Rate(period_ms, now_ms)` takes the current time at construction so it can phase-align its schedule. `due(now_ms)` returns `True` at most once per elapsed period and advances the internal schedule. Calling it again with the same timestamp returns `False` until the next period elapses.

### Shared timestamps

**Always capture `ticks_ms()` once per loop iteration** and pass the same value to every component. This prevents drift between independent clock reads:

```python
from chumicro_timing import Rate, ticks_ms

now = ticks_ms()
fast = Rate(100, now)   # 10 Hz
slow = Rate(5000, now)  # every 5 seconds

while True:
    now = ticks_ms()  # ONE reading per iteration
    if fast.due(now):
        read_sensor()
    if slow.due(now):
        send_report()
```

On a slow microcontroller, calling `ticks_ms()` separately for each component would return slightly different values. A timer that should fire at the same moment as another might not. Sharing the timestamp eliminates this class of bug.

### Resetting

`reset(now_ms)` restarts the cadence from the given timestamp:

```python
now = ticks_ms()
led_rate.reset(now)
# The next fire is now period_ms from this moment,
# regardless of when the last fire was.
```

### Behavior under late polls

`Rate` is **drift-free / phase-aligned**. When the loop runs late, `due(now)` fires and advances the *scheduled* tick by whole periods — it does not re-anchor to `now`. A 200 ms cadence keeps landing on 200, 400, 600 … even when individual polls arrive a few milliseconds late, and that jitter never accumulates. If the loop stalls for longer than one period, the missed fires are skipped rather than replayed back-to-back: `due(now)` returns `True` once and the schedule jumps forward to the next period boundary after `now`.

This is the opposite of the old `Heartbeat`, which re-anchored the next deadline to `now` on every fire and so drifted forward by each loop's late-arrival cost. `Rate` gives you the phase-locked behavior by default. If you want to see those mechanics spelled out by hand, [`examples/phase_locked_tick.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing/examples/phase_locked_tick.py) carries the deadline manually — that is exactly what `Rate` does for you internally.

## Deadlines

A `Deadline` is a single armed timeout. Arm it with the current time, then poll it:

```python
from chumicro_timing import Deadline, ticks_ms

deadline = Deadline(500, ticks_ms())  # due 500 ms from now

while not deadline.expired(ticks_ms()):
    if sensor_ready():
        break
    do_other_work()

left = deadline.remaining(ticks_ms())  # ms until due, clamped at 0
```

`expired(now)` reports whether the deadline has passed; `remaining(now)` returns the milliseconds left (clamped at `0`). `reset(now)` re-arms the same period from a new moment.

## Choosing a wait

Every ChuMicro wait answers one question.  Pick by the question, not the type.

| You want | Reach for | Lives in |
|---|---|---|
| "run this every N ms" | `Rate` | `chumicro_timing` |
| "give up after N ms" | `Deadline` | `chumicro_timing` |
| "a flag one place sets, another awaits" | `Signal` + `wait_for` | `chumicro_timing` |
| "pause this generator until the socket is readable/writable" | `ReadWait` / `WriteWait` | `chumicro_sockets` |
| "tell the runner when my service next needs the CPU" | `next_deadline` / `io_interest` on your service | the runner service contract |
| "block the loop until a task finishes, with a timeout" | `runner.run_until` | `chumicro_runner` |

`Signal` and `wait_for` live in the opt-in `chumicro_timing.waits` submodule; `ReadWait` and `WriteWait` in `chumicro_sockets.waits`.  A service reports `next_deadline` and `io_interest` as methods the runner reads each tick, not something you import.

## Using ticks directly

For custom timing logic, you can use the tick functions directly:

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

**Important**: Do not use plain subtraction (`end - start`) on tick values, and never compute a deadline as `now + delta`. The counter wraps every ~6.2 days, and plain arithmetic gives wrong results near the boundary. Use `ticks_diff()` to measure elapsed time and `ticks_add()` to offset a timestamp.

The safe default is to reach for `Deadline` rather than arm a timeout by hand. `Deadline(timeout_ms, ticks_ms())` arms via `ticks_add` internally, so the `now + delta` footgun is simply unrepresentable — you never write the wrapping arithmetic yourself. Keep `ticks_add` / `ticks_diff` for the cases where you genuinely need the raw tick values.

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

`Rate` is designed to be polled from a main loop or tick-based scheduler — it never blocks. A typical pattern:

```python
from chumicro_timing import Rate, ticks_ms

rate = Rate(1000, ticks_ms())

def on_tick() -> None:
    """Called once per scheduler tick."""
    now = ticks_ms()
    if rate.due(now):
        do_periodic_work()
```

For applications with many components, [`chumicro-runner`](https://chumicro.github.io/ChuMicro/runner/stable/) captures the timestamp once per tick and dispatches it to every registered service.

## Examples

The [examples](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing/examples) directory contains complete runnable scripts:

| Example | What it shows |
|---|---|
| `heartbeat_blink.py` | Basic periodic Rate in a main loop (the embedded hello world) |
| `multiple_heartbeats.py` | Several Rate timers at different rates sharing one timestamp |
| `timeout_check.py` | Using `ticks_diff()` for deadline-based timeout detection |
| `debounce.py` | Button debounce using `ticks_ms()` and `ticks_diff()` |
| `periodic_tick.py` | Manual periodic action — the same logic `Rate` wraps |
| `phase_locked_tick.py` | Drift-free deadline carrier by hand — the phase-locked schedule `Rate` provides built-in |
| `circuitpython_blink.py` | LED blink on CircuitPython hardware |
| `circuitpython_debounce.py` | Button debounce on CircuitPython hardware |
| `micropython_blink.py` | LED blink on MicroPython hardware |
| `micropython_debounce.py` | Button debounce on MicroPython hardware |

Simulated examples run on CPython.  Hardware examples (`circuitpython_*` / `micropython_*`) require a real board — see the setup notes in each file.

### Sensor timeouts (`timeout_check.py`)

Shows `ticks_add` for computing an absolute deadline and `ticks_diff` for checking it.  A `wait_for_sensor(timeout_ms)` helper polls a simulated sensor until it reads ready or the deadline expires, returning the elapsed time on success or `-1` on timeout.  The deadline is computed once with `ticks_add(start, timeout_ms)`; each iteration tests `ticks_diff(now, deadline) < 0` to decide whether to keep polling.

The same pattern generalises to any "fail after N ms" check — handshake completion, status-register polling, button-hold detection.

### Button debounce (`debounce.py`)

Shows `ticks_ms` and `ticks_diff` for the classic debounce pattern.  A raw button signal bounces for a few ms after each press; the debouncer records the timestamp of the last accepted transition and rejects further changes until a quiet period (`DEBOUNCE_MS`) has elapsed.

The same shape applies any time you need to suppress rapid signal changes — button presses, sensor readings near a threshold, motion-detector pulses.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) · [PyPI](https://pypi.org/project/chumicro-timing/) · [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
