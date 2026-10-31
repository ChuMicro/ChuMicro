# chumicro-knobs

**Rotary encoders and analog knobs, read as a number that holds still.**

Turn a rotary encoder and `encoder.position` counts the clicks.  Turn a potentiometer and `knob.value` lands on a step and stays there.  A fast spin is counted in full even when your loop was busy elsewhere, a knob you have let go of keeps reporting the same number, and the same code runs on CircuitPython, MicroPython, and your laptop.

## Quick example

Turn a rotary encoder to change a number on a CircuitPython board.  On a Pi Pico W, wire the encoder's two signal pins (often labelled CLK and DT) to GP16 and GP17 and its common pin to GND; on an ESP32-S2 board, use IO16 and IO17.  The pins' internal pull-ups are switched on for you.

```python
import board
from chumicro_knobs import Encoder
from chumicro_timing import ticks_ms

volume = Encoder(board.GP16, board.GP17, bounds=(0, 20))    # holds the number between 0 and 20

while True:
    now = ticks_ms()
    volume.check(now)                       # read how far the shaft turned; never waits

    if volume.just_moved:                   # True on exactly one pass per change
        print("volume", volume.position)
```

Each click you feel as the shaft turns is a *detent*, and `position` moves by one per detent.  If you have used `rotaryio.IncrementalEncoder`, `position` here is its `position`, and `check()` does the `if position != last_position` bookkeeping for you.

In a program with more going on, hand the loop to `chumicro-runner` and let a callback react to the turn:

```python
from chumicro_runner import Runner

volume.on_change = lambda detents: print("volume", volume.position)

runner = Runner()
runner.add(volume, period_ms=20)        # read the encoder fifty times a second

while True:
    now = runner.tick()
    runner.wait(now)
```

`runner.wait(now)` rests the CPU until the next job is due, and turning a knob cannot wake it, so `period_ms=20` has the runner read the encoder fifty times a second, faster than a hand turns.

## Documentation

- [User Guide](guide.md): wiring an encoder, matching its clicks, bounds and wrap, reading a potentiometer, callbacks, and wiring into a runner, then how the analog reading is held still and why a hard-spun encoder drifts
- [API Reference](api.md): every public class and method, generated from the source docstrings
- [Testing Helpers](testing.md): turning a shaft and parking a wiper from a unit test

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/knobs) · \
[PyPI](https://pypi.org/project/chumicro-knobs/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
