---
title: "chumicro-timing: timers and deadlines without sleep, for CircuitPython and MicroPython"
---

# chumicro-timing

**Timers that don't block. Your loop keeps running.**

`time.sleep(1)` stops your whole program for a second.  A button pressed during that second goes unnoticed.  With `chumicro-timing`, your `while True:` loop reads the clock on every pass and acts when a timer comes due.  A `Rate` comes due every N milliseconds.  A `Deadline` expires once, N milliseconds after it starts.  It runs on CircuitPython, MicroPython, and CPython.

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

## Documentation

- [User Guide](guide.md): blinking without `sleep`, several timers in one loop, giving up with a `Deadline`, what happens when the loop runs late, the tick functions and their rollover, and pairing with `chumicro-runner`
- [API Reference](api.md): `Rate`, `Deadline`, the `ticks_ms` / `ticks_diff` / `ticks_add` functions, and `Signal` / `wait_for` for generator tasks
- [Testing Helpers](testing.md): `FakeTicks`, a clock your tests move by hand

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) · \
[PyPI](https://pypi.org/project/chumicro-timing/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
