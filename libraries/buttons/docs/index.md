# chumicro-buttons

**Buttons that catch the press even when your loop is busy.**

Wire a button to a pin, read `button.just_pressed` in the loop you already wrote, and the press lands whether your program was idle or halfway through a slow network call.  Debouncing, long presses, auto-repeat, and double-click counting come with it, and the same code runs on CircuitPython, MicroPython, and your laptop.

## Quick example

Toggle the onboard LED with a button on a CircuitPython board.  Wire a momentary button from GP14 to GND on a Pi Pico W (on an ESP32-S2 board, IO14 and `board.IO14`).  The pin's internal pull-up is switched on for you, so the button is the only part.

```python
import board
import digitalio
from chumicro_buttons import Button
from chumicro_timing import ticks, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

button = Button(pin=board.GP14, ticks=ticks)    # ticks: the clock it times presses with

while True:
    now = ticks_ms()
    button.check(now)                   # collect what the button did; never waits

    if button.just_pressed:             # True on exactly one pass per press
        led.value = not led.value
```

`just_pressed` is true on one pass per press, so you can read it as often as you like in that pass without it firing twice, and you never clear it.  Coming from `adafruit_debouncer`: `check()` is `update()`, `just_pressed` is its `Button.pressed`, and `pressed` here is the held-down level.

In a program with more going on, hand the loop to `chumicro-runner` and let a callback react to the press:

```python
from chumicro_runner import Runner

button.on_press = lambda: print("pressed")

runner = Runner()
runner.add(button, period_ms=20)        # look at the button every 20 ms

while True:
    now = runner.tick()
    runner.wait(now)
```

`runner.tick()` checks the button and calls `on_press` on the pass a press lands.  `runner.wait(now)` rests the CPU until the next job is due.  A press cannot wake the runner, so `period_ms=20` has it look at the button every 20 ms.

## Documentation

- [User Guide](guide.md): wiring a button, reading it, long presses, repeats, and double clicks, several buttons and keypads, wiring into a runner, then tuning the debounce in software and in hardware
- [API Reference](api.md): every public class and method, generated from the source docstrings
- [Testing Helpers](testing.md): writing button logic as a unit test with `FakeButtonSource`

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons) · \
[PyPI](https://pypi.org/project/chumicro-buttons/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
