# chumicro-timing

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Timers that don't block. Your loop keeps running.**

`time.sleep(1)` stops your whole program for a second.  A button pressed during that second goes unnoticed.  With `chumicro-timing`, your `while True:` loop reads the clock on every pass and acts when a timer comes due.  A `Rate` comes due every N milliseconds.  A `Deadline` expires once, N milliseconds after it starts.  It runs on CircuitPython, MicroPython, and CPython.

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

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

Blink the onboard LED on a CircuitPython board, from a loop that never sleeps:

```python
import board
import digitalio
from chumicro_timing import Rate, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

blink = Rate(500, ticks_ms())       # comes due every 500 ms, counting from now

while True:
    now_ms = ticks_ms()             # read the clock once per pass
    if blink.due(now_ms):           # True once every 500 ms, False otherwise
        led.value = not led.value

    # Nothing above waits, so code you add here runs on every pass.
```

On MicroPython, create the LED with `led = Pin("LED", Pin.OUT)` from `machine` on a Pi Pico W, or with the LED's GPIO number on an ESP32.  Flip it with `led.value(not led.value())`.  The timing lines stay the same.

`Rate` is Arduino's BlinkWithoutDelay: `ticks_ms()` is `millis()`, and `Rate` keeps the `previousMillis` bookkeeping.

A `Deadline` gives up on something after a set time:

```python
from chumicro_timing import Deadline, ticks_ms

give_up = Deadline(5000, ticks_ms())    # expires 5 seconds from now

while True:
    now_ms = ticks_ms()
    if give_up.expired(now_ms):
        print("5 seconds are up")
        give_up.reset(now_ms)           # start another 5 seconds
```

## What's included

### Timers

| Symbol | Description |
|---|---|
| `Rate(period_ms, now_ms)` | Comes due every `period_ms`: `due(now_ms)` is `True` once per period.  A late check leaves the next one on time |
| `Deadline(period_ms, now_ms)` | Expires once, `period_ms` after `now_ms`: `expired(now_ms)`, `remaining(now_ms)`, and `reset(now_ms)` to start it over |

### Tick functions

A *tick* is a reading of a millisecond counter that rolls back to zero about every 6.2 days.  On CircuitPython the first rollover comes about 65 seconds after power-on, so code that subtracts ticks directly breaks in its first minute rather than its first week.

| Symbol | Description |
|---|---|
| `ticks_ms()` | The current tick, like Arduino's `millis()` |
| `ticks_diff(end, start)` | Milliseconds from `start` to `end`, correct across the rollover.  Use it in place of `end - start` |
| `ticks_add(ticks, delta)` | The tick `delta` milliseconds after `ticks`, correct across the rollover.  Use it in place of `ticks + delta` |

### Waits for generator tasks

`chumicro_timing.waits` pauses a [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) generator task until another part of the program signals it.  Import it by name.  A program with no generator tasks never loads it.

| Symbol | Description |
|---|---|
| `Signal()` | A flag one part of the program sets and a generator task waits on: `set(value)`, `clear()`, with `is_set` and `value` readable directly |
| `wait_for(signal, deadline_ms=None)` | Pauses a generator task until `signal` is set: `yield from wait_for(signal)` |

### Testing

| Symbol | Description |
|---|---|
| `FakeTicks(start_ms=0)` | A clock for laptop tests that moves only when the test advances it |
| `FakeTicks.advance(amount_ms)` | Move the fake clock forward |

## Where this fits

Needs no other library.  Every ChuMicro library that keeps time depends on it: [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner), [`chumicro-buttons`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons), [`chumicro-wifi`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi), [`chumicro-ntp`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp), [`chumicro-requests`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests), [`chumicro-http-server`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server), [`chumicro-mqtt`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt), and [`chumicro-websockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets).

For a real button, [`chumicro-buttons`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons) debounces it and catches a tap the loop was too busy to see.

## Platform support

Works on CPython, MicroPython, and CircuitPython.  The library picks its tick source when it loads, taking the first one in this table that the runtime has:

| Source | Runtime |
|---|---|
| `supervisor.ticks_ms` | CircuitPython 7+ |
| `time.ticks_ms` | MicroPython, some CircuitPython builds |
| `time.monotonic_ns` | CPython, some CircuitPython boards |
| `time.monotonic` | The last resort, float seconds converted to whole milliseconds |

Every source gives the same behavior.

<details>
<summary>Technical detail: tick wraparound</summary>

Every source is folded into the same 2²⁹ ms range, about 6.2 days, so the rollover lands at the same count on every runtime.  `ticks_diff` gives the right answer for two ticks up to about 3.1 days apart, half that range, which covers any timer a board program sets.

</details>

## Testing your code

`FakeTicks` from `chumicro_timing.testing` is a clock the test moves by hand, so timing logic runs on a laptop with no real waiting:

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

The `circuitpython_` and `micropython_` files need a board.  The rest also run on a laptop.

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
