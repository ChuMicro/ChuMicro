# User Guide

## Overview

A board program is one loop that runs until the power goes.  `time.sleep()` stops that loop, so while it sleeps nothing else happens: no button is read, no sensor is checked, no message is answered.  `chumicro-timing` lets the loop keep going.  Each pass reads the clock once and asks a timer whether it is time to act.

Two timers cover most programs:

- `Rate` comes due again and again, every `period_ms`.  Use it for "blink every half second" or "read the sensor every 200 ms".
- `Deadline` expires once, `period_ms` after you set it, until you `reset()` it.  Use it for "give up if there is no answer in 5 seconds".

Both are built on three tick functions, `ticks_ms()`, `ticks_diff()`, and `ticks_add()`.  A *tick* is a reading of a millisecond counter, like Arduino's `millis()`.  If you have used `adafruit_ticks`, these three behave the same way, rollover included.

## Getting started

Blink the onboard LED on a CircuitPython board, with a loop that never sleeps:

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

This is Arduino's BlinkWithoutDelay.  `Rate` keeps the `previousMillis` bookkeeping, so the loop body is one `if`.

`Rate(period_ms, now_ms)` takes the current time so it knows where its first period starts.  `due(now_ms)` returns `True` on the first pass after each period ends, and `False` on every other pass, including a second call with the same `now`.

On MicroPython the timing lines are the same and only the LED setup changes:

```python
from machine import Pin

led = Pin("LED", Pin.OUT)           # Pi Pico W; on an ESP32, the LED's GPIO number
...
        led.value(not led.value())
```

## Several timers in one loop

Give each job its own `Rate`, and read the clock once at the top of the pass:

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

Handing every timer the same `now` means timers that come due at the same moment fire on the same pass.  Reading the clock separately for each one can put one reading just before the boundary and the next just after, and two timers meant to fire together land on different passes.

## Giving up after a while

A `Deadline` answers "has this much time passed since I set it?".  Set it when you start waiting, and check it on every pass alongside whatever you are waiting for:

```python
from chumicro_timing import Deadline, ticks_ms

give_up = Deadline(500, ticks_ms())     # expires 500 ms from now

while True:
    now = ticks_ms()

    if sensor_ready():                  # your own quick check: a pin, a status register
        print("ready, with", give_up.remaining(now), "ms to spare")
        give_up.reset(now)
    elif give_up.expired(now):
        print("no answer in 500 ms")
        give_up.reset(now)              # wait another 500 ms
```

`expired(now)` is `True` once the time is up.  `remaining(now)` is the milliseconds left, and `0` once it has expired.  `reset(now)` starts the same wait over from `now`.

## Starting a timer over

Both timers take `reset(now_ms)`.  On a `Rate` it restarts the schedule, so the next `due()` comes one full period after `now`, whenever the last one was:

```python
blink.reset(ticks_ms())     # next blink in 500 ms, from this moment
```

## When the loop runs late

A pass of the loop takes time, so `due()` is usually called a few milliseconds after a period actually ends.  `Rate` schedules each period from the moment the last one was *due*, not from the moment your loop noticed it.  A 200 ms rate fires at 200, 400, 600 ms and onward, even when single passes arrive a few milliseconds late, and those few milliseconds never add up.

The simpler approach, starting each wait from the moment you noticed the last one, *drifts*: every late check pushes all the later ones back, and over an hour the delays pile up.  Arduino's BlinkWithoutDelay does it that way.  [`periodic_tick.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing/examples/periodic_tick.py) shows the drift by hand, and [`phase_locked_tick.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing/examples/phase_locked_tick.py) shows the one-line change `Rate` makes to stop it.

When the loop stalls for longer than a whole period, `Rate` skips the periods it missed rather than firing them back to back.  `due()` returns `True` once, and the schedule jumps to the next period boundary after `now`.

## Using ticks directly

For timing that fits neither timer, use the tick functions:

```python
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

start = ticks_ms()

# ... later ...
elapsed = ticks_diff(ticks_ms(), start)     # milliseconds since start

due_at = ticks_add(start, 3000)             # the tick 3 seconds after start
if ticks_diff(ticks_ms(), due_at) >= 0:
    print("3 seconds are up")
```

Never subtract ticks with `-` or add to them with `+`.  The counter rolls back to zero, and plain arithmetic gives the wrong answer across that point.  `ticks_diff()` measures between two ticks and `ticks_add()` moves a tick forward, both correctly across the rollover.

When you find yourself writing `ticks_add` to set up a timeout, reach for `Deadline` instead.  It does the `ticks_add` for you, so the mistake has nowhere to go.

## How the rollover works

Every tick is folded into a range of 2²⁹ milliseconds, about 6.2 days, after which the count starts again from zero.  On CircuitPython the first rollover comes about 65 seconds after power-on, on purpose, so code that subtracts ticks directly breaks in its first minute rather than its first week.  The small range also keeps tick arithmetic inside a board's small integers, so it never overflows on a board without big integers and never allocates memory on a board with them.

`ticks_diff()` is correct for two ticks up to about 3.1 days apart, half the range.  Any timer a board program sets fits easily.  `ticks_add()` raises `OverflowError` for a step of 3.1 days or more, and `Rate` refuses such a period with `ValueError`, because a period that long could never come due.

## Using with chumicro-runner

[`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/) runs a program built from several services in one loop.  It reads the clock once per pass and hands that reading to every service, and its `add_periodic()` does the job of a `Rate`:

```python
from chumicro_runner import Runner


def blink(now_ms: int) -> None:
    led.value = not led.value


runner = Runner()
runner.add_periodic(blink, period_ms=500)

while True:
    now = runner.tick()
    runner.wait(now)
```

When a service keeps its own `Rate` or `Deadline`, hand it the `now_ms` the runner passes in rather than calling `ticks_ms()` again, so every service agrees on the time.

## Choosing a wait

Every wait in ChuMicro answers one question.  Pick by the question:

| You want | Use | From |
|---|---|---|
| "run this every N ms" | `Rate` | `chumicro_timing` |
| "give up after N ms" | `Deadline` | `chumicro_timing` |
| "a flag one place sets, another waits on" | `Signal` + `wait_for` | `chumicro_timing.waits` |
| "pause this generator until the socket is readable or writable" | `ReadWait` / `WriteWait` | `chumicro_sockets.waits` |
| "tell the runner when my service next needs the CPU" | a `next_deadline` method on your service | the runner's service contract |
| "run the loop until a task finishes, with a timeout" | `runner.run_until` | `chumicro_runner` |

The last four belong to programs built on `chumicro-runner`.  `Signal` and `wait_for` pause a generator task until something else in the program finishes, and live in the `chumicro_timing.waits` module, which you import explicitly.  `next_deadline` is a method the runner looks for on your service, not something you import.

## Testing

`chumicro_timing.testing.FakeTicks` is a clock your test moves by hand, so timing logic runs on your laptop with no real waiting:

```python
from chumicro_timing import Rate
from chumicro_timing.testing import FakeTicks

fake = FakeTicks()
rate = Rate(100, fake.ticks_ms())

fake.advance(100)
assert rate.due(fake.ticks_ms()) is True
```

The [testing page](testing.md) covers `Deadline` and using the fake with a runner.

## Platform notes

The library picks a clock when it is imported, trying these in order and using the first your runtime has:

| Order | Source | Runtime |
|---|---|---|
| 1 | `supervisor.ticks_ms` | CircuitPython 7+ |
| 2 | `time.ticks_ms` | MicroPython, some CircuitPython builds |
| 3 | `time.monotonic_ns` | CPython, some CircuitPython boards |
| 4 | `time.monotonic` | Last resort, float seconds turned into whole milliseconds |

Every source is folded into the same 2²⁹ ms range, so your code behaves the same whichever one is in use.

## Examples

The [examples](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing/examples) are listed in reading order, simplest first.  The `circuitpython_` and `micropython_` files need a board; the rest also run on your laptop.

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

A `Rate` starts a new attempt once a second, and each attempt calls `give_up.reset(now)` on a 500 ms `Deadline`.  Every pass of the loop asks the pretend sensor whether it is ready and asks the deadline whether it has expired, and whichever answers first ends the attempt.  The same shape fits any "fail after N ms" check: waiting for a handshake, a status bit, or a reply.

### Debouncing by hand (`debounce.py`)

A button's contacts bounce for a few milliseconds when they meet or part, so one press reads as several.  The loop remembers when it last accepted a change and ignores any further change for `DEBOUNCE_MS` after it, using `ticks_diff` to measure.  The same idea quiets any signal that flickers as it changes: a sensor reading near a threshold, a motion detector's pulse.  For buttons in a real project, [`chumicro-buttons`](https://chumicro.com/ChuMicro/buttons/stable/) does this and catches taps a busy loop would miss.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) · \
[PyPI](https://pypi.org/project/chumicro-timing/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
