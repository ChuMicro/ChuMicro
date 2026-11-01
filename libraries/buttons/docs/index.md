---
title: "chumicro-buttons: debounced buttons that catch every press, for CircuitPython and MicroPython"
---

# chumicro-buttons

**Buttons that catch the press even when your loop is busy.**

`chumicro-buttons` reads a button wired to a pin and reports each press through `button.just_pressed`, in the `while True:` loop you already have.  A press lands whether the program was idle or halfway through a slow network call.  Debouncing, long presses, auto-repeat, and double-click counting come with it.  The same code runs on CircuitPython, MicroPython, and CPython.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_buttons

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_buttons

# CPython
pip install chumicro-buttons
```

The `Runner` loop in the quick example comes from `chumicro-runner`.  Install it the same way.

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

Toggle the onboard LED with a button on a CircuitPython board.  On a Pi Pico W, wire a momentary button from GP14 to GND.  On an ESP32-S2 board, use IO14 and `board.IO14`.  The library switches on the pin's internal pull-up, so the button is the only part:

```python
import board
import digitalio
from chumicro_buttons import Button
from chumicro_timing import ticks, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

button = Button(pin=board.GP14, ticks=ticks)    # ticks: the clock it times presses with

while True:
    now_ms = ticks_ms()
    button.check(now_ms)                # collect what the button did, without waiting

    if button.just_pressed:             # True on exactly one pass per press
        led.value = not led.value
```

The loop never pauses, so code you add to it keeps running between presses.  `just_pressed` is `True` on exactly one pass per press.  Reading it twice in that pass gives the same answer.  Nothing needs to clear it.

On MicroPython, pass a `machine.Pin`: `Button(pin=Pin(14), ticks=ticks)`.

In a program with more going on, hand the loop to [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/) and let a callback react to the press:

```python
from chumicro_runner import Runner

button.on_press = lambda: print("pressed")

runner = Runner()
runner.add(button, period_ms=20)        # look at the button every 20 ms

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

`runner.tick()` checks the button and calls `on_press` on the pass a press lands.  `runner.wait(now_ms)` sleeps until the next job is due.  A press cannot wake the runner, so `period_ms=20` has it look at the button every 20 ms.  Without `period_ms`, a press waits for whatever wakes the runner next, which can be seconds in a program with a slow job.

## Documentation

- [User Guide](guide.md): wiring a button, reading it, long presses, repeats, and double clicks, several buttons and keypads, the runner pattern, and tuning the debounce in software and in hardware
- [API Reference](api.md): `Button`, `Buttons`, and `KeyMatrix`, with their readings and callbacks
- [Testing Helpers](testing.md): button logic as a unit test with `FakeButtonSource`

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons) · \
[PyPI](https://pypi.org/project/chumicro-buttons/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
