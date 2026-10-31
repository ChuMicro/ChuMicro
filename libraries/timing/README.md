# chumicro-timing

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Timers that don't block. Your loop keeps running.**

`time.sleep(1)` stops your whole program for a second, and a button pressed during that second goes unnoticed.  `chumicro-timing` keeps the loop running and tells you when it is time to act: a `Rate` comes due every N milliseconds, and a `Deadline` expires once, N milliseconds after you set it.  It runs on CircuitPython, MicroPython, and CPython, needs no other library, and every other ChuMicro library keeps time with it.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_timing

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# CPython
pip install chumicro-timing
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

## Quick example

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

If you know Arduino, this is BlinkWithoutDelay: `ticks_ms()` is `millis()`, and `Rate` keeps the `previousMillis` bookkeeping for you.

On MicroPython, set the LED up with `from machine import Pin` and `led = Pin("LED", Pin.OUT)` on a Pi Pico W (or the LED's GPIO number on an ESP32), and flip it with `led.value(not led.value())`.  The timing lines stay the same.

To give up on something after a while instead, use a `Deadline`:

```python
from chumicro_timing import Deadline, ticks_ms

give_up = Deadline(5000, ticks_ms())    # expires 5 seconds from now

while True:
    now = ticks_ms()
    if give_up.expired(now):
        print("5 seconds are up")
        give_up.reset(now)              # start another 5 seconds
```

## What's included

### Timers

| Symbol | Description |
|---|---|
| `Rate(period_ms, now_ms)` | Comes due every `period_ms`: `due(now)` is `True` once per period.  A late check never pushes the schedule back |
| `Deadline(period_ms, now_ms)` | Expires once, `period_ms` after `now_ms`: `expired(now)`, `remaining(now)`, and `reset(now)` to start it over |

### Tick functions

A *tick* is a reading of a millisecond counter that rolls back to zero about every 6.2 days.  On CircuitPython the first rollover comes about 65 seconds after power-on, so code that subtracts ticks directly breaks in its first minute rather than its first week.

| Symbol | Description |
|---|---|
| `ticks_ms()` | The current tick, like Arduino's `millis()` |
| `ticks_diff(end, start)` | Milliseconds from `start` to `end`, correct across the rollover.  Use it in place of `end - start` |
| `ticks_add(ticks, delta)` | The tick `delta` milliseconds after `ticks`, correct across the rollover.  Use it in place of `ticks + delta` |

### Waits for generator tasks (`chumicro_timing.waits`)

For [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) tasks written as generators that pause until something finishes.  A program with a plain `while True:` loop never needs these.  Import the module explicitly.

| Symbol | Description |
|---|---|
| `Signal()` | A flag one part of the program sets and a generator waits on: `set(value)`, `clear()`, with `is_set` and `value` readable directly |
| `wait_for(signal, deadline_ms=None)` | Pauses a generator until `signal` is set: `yield from wait_for(signal)` |

### Testing

| Symbol | Description |
|---|---|
| `FakeTicks(start_ms=0)` | A clock for tests on your laptop that moves only when you tell it to |
| `FakeTicks.advance(amount_ms)` | Move the fake clock forward |

## Where this fits

Needs no other ChuMicro library.  Every ChuMicro library that keeps time builds on it: [`runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner), [`sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets), [`ntp`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp), [`requests`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests), [`http_server`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server), [`mqtt`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt), [`websockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets).

## Platform support

You don't need to pick a tick source.  The library picks the best one available on your runtime.  Behavior is identical regardless of which source is used.

| Source | Runtime |
|---|---|
| `supervisor.ticks_ms` | CircuitPython 7+ |
| `time.ticks_ms` | MicroPython, some CircuitPython builds |
| `time.monotonic_ns` | CPython, some CircuitPython boards |
| `time.monotonic` | Final fallback (float seconds → int ms) |

The library tries them top-to-bottom and uses the first one your runtime supports.

<details>
<summary>Technical detail: tick wraparound</summary>

Every source is folded into the same 2²⁹ ms range (about 6.2 days), so the rollover lands at the same count on every runtime.  `ticks_diff` gives the right answer for two ticks up to about 3.1 days apart, half that range, which covers any timer a board program sets.

</details>

## Testing your code

The `chumicro_timing.testing` module provides `FakeTicks`, a clock your test moves by hand, so timing logic runs on your laptop with no real waiting:

```python
from chumicro_timing import Rate
from chumicro_timing.testing import FakeTicks

fake = FakeTicks()
rate = Rate(100, fake.ticks_ms())

assert rate.due(fake.ticks_ms()) is False

fake.advance(100)
assert rate.due(fake.ticks_ms()) is True
```

## Examples

In reading order, simplest first.  The `circuitpython_` and `micropython_` files need a board; the rest also run on your laptop.

| Example | What it shows |
|---|---|
| [`circuitpython_blink.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/circuitpython_blink.py), [`micropython_blink.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/micropython_blink.py) | The quick example as a full program: the onboard LED blinks once a second |
| [`rate_blink.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/rate_blink.py) | The same loop printing `LED on` and `LED off`, so it runs without a board |
| [`multiple_rates.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/multiple_rates.py) | Three `Rate` timers at three speeds in one loop |
| [`timeout_check.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/timeout_check.py) | A `Deadline` that gives up on a slow sensor, with a `Rate` that starts a new attempt each second |
| [`circuitpython_debounce.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/circuitpython_debounce.py), [`micropython_debounce.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/micropython_debounce.py) | A button that toggles the LED, debounced by hand with `ticks_diff` |
| [`debounce.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/debounce.py) | The same debounce on a pretend bouncing button, printing each bounce it ignores |
| [`periodic_tick.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/periodic_tick.py) | Arduino's BlinkWithoutDelay written by hand, and how its schedule slips a little more each second |
| [`phase_locked_tick.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/phase_locked_tick.py) | The one-line change that stops the slip, which is what `Rate` does inside |

For buttons in a real project, [`chumicro-buttons`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons) debounces for you and catches a tap your loop was too busy to see.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/timing/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/timing/experimental/)**

## Find this library

- **PyPI:** [chumicro-timing](https://pypi.org/project/chumicro-timing/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_timing) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_timing)
- **Source:** [libraries/timing](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
