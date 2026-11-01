---
title: "chumicro-knobs: rotary encoders and analog knobs for CircuitPython and MicroPython"
---

# chumicro-knobs

**Rotary encoders and analog knobs, read as a number that holds still.**

`encoder.position` counts the clicks of a rotary encoder.  `knob.value` lands a potentiometer on a numbered step and keeps it there.  A fast spin counts in full even when the loop was busy elsewhere.  A knob left alone keeps reporting the same number.  The same code runs on CircuitPython, MicroPython, and CPython.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_knobs

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_knobs

# CPython
pip install chumicro-knobs
```

The quick example reads the clock with `chumicro-timing`.  Its `Runner` loop comes from `chumicro-runner`.  Install both the same way.

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

Turn a rotary encoder to change a number on a CircuitPython board.  On a Pi Pico W, wire the encoder's two signal pins, often labelled CLK and DT, to GP16 and GP17, and its common pin to GND.  On an ESP32-S2 board, use IO16 and IO17.  The library switches on the pins' internal pull-ups:

```python
import board
from chumicro_knobs import Encoder
from chumicro_timing import ticks_ms

volume = Encoder(board.GP16, board.GP17, bounds=(0, 20))    # holds the number between 0 and 20

while True:
    now_ms = ticks_ms()
    volume.check(now_ms)                    # read how far the shaft turned, without waiting

    if volume.just_moved:                   # True on exactly one pass per change
        print("volume", volume.position)
```

Each click you feel as the shaft turns is a *detent*.  `position` moves by one per detent.  An encoder whose `position` moves only on every other click wants `detent_steps=2`.

On MicroPython, pass `machine.Pin` objects: `Encoder(Pin(16), Pin(17), bounds=(0, 20))`.

In a program with more going on, hand the loop to [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/) and let a callback react to the turn:

```python
from chumicro_runner import Runner

volume.on_change = lambda detents: print("volume", volume.position)

runner = Runner()
runner.add(volume, period_ms=20)        # read the encoder fifty times a second

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

`runner.tick()` checks the encoder and calls `on_change` on the pass it turned.  `runner.wait(now_ms)` sleeps until the next job is due.  Turning a knob cannot wake the runner, so `period_ms=20` has it read the encoder fifty times a second, faster than a hand turns.

## Documentation

- [User Guide](guide.md): wiring an encoder, matching its clicks, bounds and wrap, reading a potentiometer, callbacks, and the runner pattern, then how the analog reading holds still and why a hard-spun encoder drifts
- [API Reference](api.md): `Encoder` and `AnalogKnob`, with their readings, callbacks, and defaults
- [Testing Helpers](testing.md): turning a shaft and parking a wiper from a unit test

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/knobs) · \
[PyPI](https://pypi.org/project/chumicro-knobs/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
