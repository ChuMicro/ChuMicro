---
title: "chumicro-timing: timers and deadlines without sleep, for CircuitPython and MicroPython"
---

# chumicro-timing

**Timers that don't block, for CircuitPython, MicroPython, and CPython.**

`time.sleep(1)` stops your whole program for a second, and a button pressed during that second goes unnoticed.  `chumicro-timing` keeps the loop running and tells you when it is time to act: a `Rate` comes due every N milliseconds, and a `Deadline` expires once, N milliseconds after you set it.  Read the clock once per pass with `ticks_ms()`, Arduino's `millis()` under another name, and hand that reading to each timer.  The millisecond counter rolls back to zero every few days, and every timer here stays correct across that rollover.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_timing

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# CPython
pip install chumicro-timing
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

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

## Documentation

- [User Guide](guide.md): blinking without `sleep`, several timers in one loop, giving up with a `Deadline`, what happens when the loop runs late, the tick functions and their rollover, pairing with `chumicro-runner`
- [API Reference](api.md): the wrap-safe `ticks_ms` / `ticks_diff` / `ticks_add` helpers, the `Deadline` and `Rate` value objects, and the `Signal` / `wait_for` wait vocabulary
- [Testing Helpers](testing.md): using `FakeTicks` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) · \
[PyPI](https://pypi.org/project/chumicro-timing/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
