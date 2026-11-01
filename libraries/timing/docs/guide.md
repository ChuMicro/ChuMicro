# User Guide

## Overview

A board program is one loop that runs until the power goes.  `time.sleep()` stops that loop.  A button tap that starts and ends during the sleep goes unread.  `chumicro-timing` keeps the loop running.  Each pass of the loop reads the clock once and asks a timer whether its moment has come.

- `Rate` comes due every `period_ms`, again and again.  It runs jobs like "blink every half second" or "read the sensor every 200 ms".
- `Deadline` expires once, `period_ms` after it was set, and stays expired until `reset()`.  It bounds a wait like "give up if no answer comes in 5 seconds".

Both timers run on the tick functions `ticks_ms()`, `ticks_diff()`, and `ticks_add()`.  A *tick* is a reading of a millisecond counter, like Arduino's `millis()`.  The three functions behave like `adafruit_ticks`, rollover included.

## Getting started

This program blinks the onboard LED of a CircuitPython board from a loop that never sleeps:

```python
import board
import digitalio
from chumicro_timing import Rate, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

blink = Rate(500, ticks_ms())       # comes due every 500 ms, counting from now

while True:
    now = ticks_ms()                # read the clock once per pass
    if blink.due(now):              # True once every 500 ms, False otherwise
        led.value = not led.value

    # Nothing above waits, so code you add here runs on every pass.
```

The program does the job of Arduino's BlinkWithoutDelay sketch.  `Rate` keeps the `previousMillis` bookkeeping, which leaves one `if` in the loop body.

`Rate(period_ms, now_ms)` counts its first period from `now_ms`.  `due(now_ms)` returns `True` on the first call after each period ends.  Every other call returns `False`, a second call with the same `now_ms` included.

The MicroPython version drives the LED through `machine.Pin`.  Its timing lines are the same as the CircuitPython program's:

```python
from machine import Pin
from chumicro_timing import Rate, ticks_ms

led = Pin("LED", Pin.OUT)           # Pi Pico W; on an ESP32, the LED's GPIO number

blink = Rate(500, ticks_ms())

while True:
    now = ticks_ms()
    if blink.due(now):
        led.value(not led.value())
```

## Several timers in one loop

Each job gets its own `Rate`.  Every timer reads the one clock reading taken at the top of the pass:

```python
from chumicro_timing import Rate, ticks_ms

now = ticks_ms()
fast = Rate(100, now)       # 10 times a second
slow = Rate(5000, now)      # every 5 seconds

while True:
    now = ticks_ms()        # one reading per pass, shared by every timer
    if fast.due(now):
        print("read the sensor")
    if slow.due(now):
        print("send a report")
```

Timers that share one `now` and come due at the same moment fire on the same pass.  With a separate clock reading per timer, one reading can land just before a period boundary and the next just after it, which splits two timers meant to fire together across two passes.

## Giving up after a while

A `Deadline` reports whether a set amount of time has passed since it was set.  A program sets one when a wait begins, then checks it on every pass next to the check for the thing it waits on:

```python
from chumicro_timing import Deadline, ticks_ms


def sensor_ready():
    return False                        # your own quick check: a pin, a status register


give_up = Deadline(500, ticks_ms())     # expires 500 ms from now

while True:
    now = ticks_ms()

    if sensor_ready():
        print("ready, with", give_up.remaining(now), "ms to spare")
        give_up.reset(now)
    elif give_up.expired(now):
        print("no answer in 500 ms")
        give_up.reset(now)              # wait another 500 ms
```

`expired(now_ms)` returns `True` once the time is up.  `remaining(now_ms)` returns the milliseconds left, down to `0`.  `reset(now_ms)` starts the same wait again from `now_ms`.

## Starting a timer over

`Rate` has `reset(now_ms)` too.  It restarts the schedule, so the next `due()` lands one full period after `now_ms`, wherever the last one fell:

```python
blink.reset(ticks_ms())     # next blink in 500 ms, from this moment
```

## When the loop runs late

Each pass of the loop takes time, so `due()` usually runs a few milliseconds after a period ends.  `Rate` schedules the next period from the moment the last one was *due*, rather than from the moment the loop noticed it.  A 200 ms `Rate` fires at 200, 400, and 600 ms.  The few milliseconds each pass arrives late never add up.

Arduino's BlinkWithoutDelay starts each wait from the moment the loop noticed the last one.  That schedule *drifts*.  Every late check pushes all the later ones back.  Over an hour the delays pile up.  [`periodic_tick.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing/examples/periodic_tick.py) writes the drifting schedule out by hand.  [`phase_locked_tick.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing/examples/phase_locked_tick.py) makes the one-line change that stops the drift, which is the change `Rate` makes inside.

After a stall longer than a whole period, `Rate` skips the periods it missed instead of firing them back to back.  `due()` returns `True` once.  The schedule then jumps to the first period boundary after `now_ms`.

## Using ticks directly

The tick functions handle timing that fits neither timer:

```python
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

start = ticks_ms()

# ... later ...
elapsed = ticks_diff(ticks_ms(), start)     # milliseconds since start

due_at = ticks_add(start, 3000)             # the tick 3 seconds after start
if ticks_diff(ticks_ms(), due_at) >= 0:
    print("3 seconds are up")
```

Plain `-` and `+` give wrong answers across the point where the counter rolls back to zero.  `ticks_diff()` measures the distance between two ticks.  `ticks_add()` moves a tick forward.  Both stay correct across the rollover.

A timeout built by hand from `ticks_add` and `ticks_diff` repeats what `Deadline` already does.

## How the rollover works

Every tick sits in a range of 2²⁹ milliseconds, about 6.2 days.  At the end of the range the count starts again from zero.  CircuitPython starts its count about 65 seconds short of the end, so code that subtracts ticks directly fails in its first minute instead of its first week.

The range also keeps tick arithmetic inside a board's small integers.  A board without big integers never overflows on tick math.  A board with them never allocates memory for it.

`ticks_diff()` stays correct for two ticks up to about 3.1 days apart, half the range.  `ticks_add()` raises `OverflowError` for a step of 3.1 days or more.  `Rate` raises `ValueError` for a period that long, because such a period could never come due.

## Using with chumicro-runner

In a program built on [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/guide/), `runner.add_periodic()` does the job of a `Rate` ([Timed jobs](https://chumicro.com/ChuMicro/runner/stable/guide/#timed-jobs)).  A service that keeps its own `Rate` or `Deadline` hands it the `now_ms` the runner passes in, instead of calling `ticks_ms()` again, so every service agrees on the time.

## Choosing a wait

| You want | Use | From |
|---|---|---|
| "run this every N ms" | `Rate` | `chumicro_timing` |
| "give up after N ms" | `Deadline` | `chumicro_timing` |
| "a flag one place sets, another waits on" | `Signal` + `wait_for` | `chumicro_timing.waits` |
| "pause this generator until the socket is readable or writable" | `ReadWait` / `WriteWait` | `chumicro_sockets.waits` |
| "tell the runner when my service next needs the CPU" | a `next_deadline` method on your service | the runner's [service contract](https://chumicro.com/ChuMicro/runner/stable/guide/#the-service-contract) |
| "run the loop until a task finishes, with a timeout" | `runner.run_until` | `chumicro_runner` |

The last four rows apply to programs built on `chumicro-runner`.  `Signal` and `wait_for` pause a generator task until another part of the program calls `set()` on the signal ([Waiting for a callback](https://chumicro.com/ChuMicro/runner/stable/guide/#waiting-for-a-callback)).  Both live in the `chumicro_timing.waits` module, which `import chumicro_timing` leaves unloaded.  `next_deadline` is a method the runner calls on a service.

## Testing

`chumicro_timing.testing.FakeTicks` is a clock that moves only when a test calls `advance()`.  Timing logic tested against it runs on a laptop with no real waiting:

```python
from chumicro_timing import Rate
from chumicro_timing.testing import FakeTicks

fake = FakeTicks()
rate = Rate(100, fake.ticks_ms())

fake.advance(100)
assert rate.due(fake.ticks_ms()) is True
```

The [testing page](testing.md) drives a `Deadline` the same way.

## Platform notes

On import, the library takes the first clock source the runtime has, in this order:

| Order | Source | Runtime |
|---|---|---|
| 1 | `supervisor.ticks_ms` | CircuitPython 7+ |
| 2 | `time.ticks_ms` | MicroPython, some CircuitPython builds |
| 3 | `time.monotonic_ns` | CPython, some CircuitPython boards |
| 4 | `time.monotonic` | Last resort, float seconds turned into whole milliseconds |

Every source folds into the same 2²⁹ ms range, so a program behaves the same on any of them.

## Examples

The `circuitpython_` and `micropython_` [examples](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing/examples) need a board.  The rest also run on a laptop.

| Example | What it shows |
|---|---|
| `circuitpython_blink.py`, `micropython_blink.py` | Getting started as a full program: the onboard LED blinks once a second |
| `rate_blink.py` | The same loop printing `LED on` and `LED off`, so it runs without a board |
| `multiple_rates.py` | Three `Rate` timers at three speeds in one loop |
| `timeout_check.py` | A `Deadline` that gives up on a slow sensor, with a `Rate` that starts a new attempt each second |
| `circuitpython_debounce.py`, `micropython_debounce.py` | A button that toggles the LED, debounced by hand with `ticks_diff` |
| `debounce.py` | The same debounce on a pretend bouncing button, printing each bounce it ignores |
| `periodic_tick.py` | Arduino's BlinkWithoutDelay written by hand, and how its schedule slips a little more each second |
| `phase_locked_tick.py` | The one-line change that stops the slip, which is what `Rate` does inside |

### Giving up on a slow sensor (`timeout_check.py`)

A `Rate` starts an attempt once a second.  Each attempt resets a 500 ms `Deadline`.  Every pass asks the pretend sensor whether it is ready and asks the deadline whether it has expired.  The first yes ends the attempt.  The same pairing fits any check that fails after N ms, such as a handshake, a status bit, or a reply.

### Debouncing by hand (`debounce.py`)

A button's contacts bounce for a few milliseconds when they meet or part, so one press reads as several.  The loop remembers when it last accepted a change and ignores further changes for `DEBOUNCE_MS` after it, measured with `ticks_diff`.  The same idea quiets any signal that flickers as it changes, such as a sensor reading near a threshold.  [`chumicro-buttons`](https://chumicro.com/ChuMicro/buttons/stable/guide/) does this for real buttons and also catches taps a busy loop would miss.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) · \
[PyPI](https://pypi.org/project/chumicro-timing/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
